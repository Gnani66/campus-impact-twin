"""
Batched writer for `telemetry_readings`.

Takes validated `TelemetryMessage` instances, keeps them in a
bounded buffer, and inserts them in chunks on a flush interval.

Design notes:

* The buffer is bounded. Reaching `max_buffer_rows` forces a
  flush rather than letting memory grow.
* A flush takes the buffer under a lock and clears it, so two
  concurrent flushes can never insert the same rows twice.
* Failures are never silent. Chunks are retried with
  exponential backoff, and if a chunk still fails the rows are
  put back at the front of the buffer and a
  `TelemetryWriterError` is raised, so the caller decides what
  to do with them.
* The Supabase client is synchronous and thread-local, so every
  insert is a blocking call. The `*_async` methods move it off
  the event loop with `asyncio.to_thread`; nothing here blocks
  a running loop.
* Insertion is injected, so tests never touch Supabase.

Nothing starts a background task at import time. Callers own
the lifecycle: `enqueue`, `flush`, `close`, or `run_flusher`.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
)

from app.db.supabase import get_supabase
from app.telemetry.models import TelemetryMessage


logger = logging.getLogger(__name__)


TABLE = "telemetry_readings"

# PostgREST accepts at most 1000 rows in one insert, so the
# default chunk leaves room well below that ceiling.
DEFAULT_CHUNK_SIZE = 200
DEFAULT_MAX_BUFFER_ROWS = 500
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.05
DEFAULT_MAX_BACKOFF_SECONDS = 1.0


class TelemetryWriterError(RuntimeError):
    """
    Raised when readings could not be persisted. The affected
    rows are still in the buffer.
    """


class TelemetryWriterClosed(RuntimeError):
    """
    Raised when a closed writer is used again.
    """


@dataclass
class WriterStats:
    """
    Counters for logs and health checks. Nothing here is
    persisted.
    """

    enqueued_rows: int = 0
    inserted_rows: int = 0
    failed_rows: int = 0
    flushes: int = 0
    chunks: int = 0
    retries: int = 0
    forced_flushes: int = 0


@dataclass(frozen=True)
class FlushResult:
    inserted_rows: int = 0
    chunks: int = 0
    buffer_size: int = 0


class TelemetryWriter:
    """
    Buffers readings and writes them to Supabase.

    `insert_fn` receives a list of row dictionaries. The
    default implementation talks to Supabase; tests pass a
    callable instead.
    """

    def __init__(
        self,
        insert_fn: Optional[Callable[[List[Dict]], None]] = None,
        client: object = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_buffer_rows: int = DEFAULT_MAX_BUFFER_ROWS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        sleep_fn: Callable[[float], None] = None,
        flush_interval_seconds: Optional[float] = None,
        app_settings: object = None,
        on_persisted: Optional[
            Callable[[List[Dict[str, Any]]], None]
        ] = None,
    ) -> None:
        from app.core.config import settings

        settings = (
            app_settings if app_settings is not None else settings
        )

        if chunk_size < 1:
            raise ValueError(
                f"chunk_size must be >= 1, got {chunk_size}"
            )

        if max_buffer_rows < chunk_size:
            raise ValueError(
                "max_buffer_rows must be at least chunk_size "
                f"({chunk_size}), got {max_buffer_rows}"
            )

        self._insert_fn = insert_fn
        self._on_persisted = on_persisted
        self._client = client
        self._chunk_size = chunk_size
        self._max_buffer_rows = max_buffer_rows
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._sleep_fn = sleep_fn or _default_sleep
        self._flush_interval_seconds = (
            float(settings.telemetry_flush_seconds)
            if flush_interval_seconds is None
            else float(flush_interval_seconds)
        )

        self._buffer: List[Dict] = []
        self._buffer_lock = threading.Lock()
        # Serialises flushes so two callers cannot interleave
        # chunk inserts for the same rows.
        self._flush_lock = threading.Lock()
        self._closed = False
        self.stats = WriterStats()

    # --- properties ----------------------------------------------

    @property
    def flush_interval_seconds(self) -> float:
        return self._flush_interval_seconds

    @property
    def buffer_size(self) -> int:
        with self._buffer_lock:
            return len(self._buffer)

    @property
    def is_closed(self) -> bool:
        return self._closed

    # --- input ---------------------------------------------------

    def enqueue(
        self, message: TelemetryMessage
    ) -> None:
        """
        Adds one validated reading to the buffer.

        Reaching `max_buffer_rows` forces a flush. If that
        flush fails the exception propagates and the rows stay
        buffered, so nothing is dropped quietly.
        """

        if not isinstance(message, TelemetryMessage):
            raise TypeError(
                "enqueue expects a TelemetryMessage, got "
                f"{type(message).__name__}"
            )

        should_flush = False

        with self._buffer_lock:
            if self._closed:
                raise TelemetryWriterClosed(
                    "writer is closed"
                )

            self._buffer.append(message.to_row())
            self.stats.enqueued_rows += 1
            should_flush = len(self._buffer) >= (
                self._max_buffer_rows
            )

        if should_flush:
            self.stats.forced_flushes += 1
            self.flush()

    async def enqueue_async(
        self, message: TelemetryMessage
    ) -> None:
        """
        `enqueue` without blocking the event loop.

        `to_row()` is CPU-only, so only the forced flush needs
        to leave the loop.
        """

        await asyncio.to_thread(self.enqueue, message)

    # --- output --------------------------------------------------

    def flush(self) -> FlushResult:
        """
        Inserts everything buffered, in chunks.

        Flushing an empty buffer is a no-op and returns a zero
        result. Rows that fail are restored to the buffer, so
        the caller can retry later without losing them.
        """

        with self._flush_lock:
            with self._buffer_lock:
                if not self._buffer:
                    logger.debug(
                        "Telemetry flush requested with an "
                        "empty buffer"
                    )
                    return FlushResult(
                        inserted_rows=0,
                        chunks=0,
                        buffer_size=0,
                    )

                batch = list(self._buffer)
                self._buffer.clear()

            try:
                inserted = self._insert_with_retry(batch)
            except Exception as exc:
                with self._buffer_lock:
                    # Oldest first, so ordering is preserved.
                    self._buffer[:0] = batch
                    self.stats.failed_rows += len(batch)

                logger.exception(
                    "Telemetry flush failed for %d rows; "
                    "rows kept in buffer",
                    len(batch),
                )

                raise TelemetryWriterError(
                    f"failed to insert {len(batch)} telemetry "
                    f"rows: {exc}"
                ) from exc

            self.stats.inserted_rows += inserted
            self.stats.flushes += 1

            if self._on_persisted is not None:
                self._notify_persisted(batch)

            logger.info(
                "Telemetry flush inserted %d rows in %d "
                "chunk(s)",
                inserted,
                max(1, (len(batch) + self._chunk_size - 1)
                    // self._chunk_size),
            )

            return FlushResult(
                inserted_rows=inserted,
                chunks=self._chunk_size_count(batch),
                buffer_size=self.buffer_size,
            )

    async def flush_async(self) -> FlushResult:
        """
        `flush` moved off the event loop, because the Supabase
        client is synchronous.
        """

        return await asyncio.to_thread(self.flush)

    def close(self, drain: bool = True) -> FlushResult:
        """
        Stops accepting readings, optionally flushing what is
        buffered. Closing twice is safe and does nothing the
        second time.
        """

        if self._closed:
            return FlushResult()

        result = self.flush() if drain else FlushResult()

        with self._buffer_lock:
            self._closed = True

        logger.info(
            "Telemetry writer closed (%s)",
            "drained" if drain else "buffer discarded",
        )

        return result

    async def close_async(
        self, drain: bool = True
    ) -> FlushResult:
        return await asyncio.to_thread(self.close, drain)

    # --- periodic flush ------------------------------------------

    async def run_flusher(
        self,
        stop: Optional[asyncio.Event] = None,
        max_flushes: Optional[int] = None,
    ) -> None:
        """
        Flushes every `flush_interval_seconds` until the stop
        event is set or the task is cancelled.

        Owned by the caller: nothing calls this automatically.
        `max_flushes` exists for tests and short demos.
        """

        completed = 0

        try:
            while (
                stop is None or not stop.is_set()
            ) and (
                max_flushes is None
                or completed < max_flushes
            ):
                if await _sleep_or_stop(
                    self._flush_interval_seconds, stop
                ):
                    break

                result = await self.flush_async()
                completed += 1

                if result.inserted_rows:
                    logger.debug(
                        "Periodic telemetry flush inserted "
                        "%d rows",
                        result.inserted_rows,
                    )
        except asyncio.CancelledError:
            logger.info(
                "Periodic telemetry flusher cancelled"
            )
            raise

    # --- internals -----------------------------------------------

    def _notify_persisted(
        self,
        batch: List[Dict[str, Any]],
    ) -> None:
        """
        Hands the persisted rows to the observer, if any.

        The intelligence engine is wired in here so it only sees
        rows that are already durable. An observer failure is
        logged and swallowed: telemetry is the system of record,
        and losing it because incident detection had a bad day
        would be the wrong trade.
        """

        try:
            self._on_persisted(batch)
        except Exception:
            logger.exception(
                "Telemetry observer failed for %d rows",
                len(batch),
            )

    def _chunk_size_count(self, rows: List[Dict]) -> int:
        if not rows:
            return 0

        return (len(rows) + self._chunk_size - 1) // self._chunk_size

    def _insert_with_retry(self, rows: List[Dict]) -> int:
        """
        Inserts in chunks, retrying each chunk with
        exponential backoff. Raises when a chunk is exhausted.
        """

        inserted = 0

        for start in range(0, len(rows), self._chunk_size):
            chunk = rows[start:start + self._chunk_size]
            attempt = 0

            while True:
                try:
                    self._insert(chunk)
                except Exception as exc:
                    if attempt >= self._max_retries:
                        logger.error(
                            "Telemetry chunk of %d rows failed "
                            "after %d retries: %s",
                            len(chunk),
                            attempt,
                            exc,
                        )
                        raise

                    delay = min(
                        self._backoff_seconds
                        * (2 ** attempt),
                        self._max_backoff_seconds,
                    )

                    attempt += 1
                    self.stats.retries += 1

                    logger.warning(
                        "Telemetry chunk insert failed "
                        "(attempt %d/%d), retrying in %.2fs: %s",
                        attempt,
                        self._max_retries + 1,
                        delay,
                        exc,
                    )

                    self._sleep_fn(delay)
                    continue

                inserted += len(chunk)
                self.stats.chunks += 1
                break

        return inserted

    def _insert(self, rows: List[Dict]) -> None:
        if self._insert_fn is not None:
            self._insert_fn(rows)
            return

        client = self._client or get_supabase()

        client.table(TABLE).insert(rows).execute()


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


async def _sleep_or_stop(
    seconds: float,
    stop: Optional[asyncio.Event],
) -> bool:
    """
    Sleeps, but returns True early if the stop event fires.
    """

    if stop is None:
        await asyncio.sleep(seconds)
        return False

    try:
        await asyncio.wait_for(
            stop.wait(), timeout=seconds
        )
        return True
    except asyncio.TimeoutError:
        return False