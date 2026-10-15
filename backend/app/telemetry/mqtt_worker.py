"""
MQTT telemetry ingestion worker.

Subscribes to the campus telemetry topics, validates every
message against Stage 3's contract, and hands the survivors
to the Stage 5A writer.

Validation, in order, for each message:

1. topic parsed with `topics.parse_topic` (strict structure)
2. payload decoded as UTF-8 and parsed as JSON
3. payload validated as a `TelemetryMessage`
4. the sensor UUID in the payload must match the topic's
5. the sensor must exist in the registry
6. its metric and unit must match the registry
7. any location identifiers present must match the registry;
   absent ones are filled in from it

Anything that fails is counted by reason and logged. One bad
message never stops the worker.

The Supabase-backed registry is synchronous, so it is loaded
once through `anyio.to_thread.run_sync` and then reused, never
queried per message and never called on the event loop.

Nothing starts at import: callers own `start()` / `stop()`.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import (
    Callable,
    Dict,
    Optional,
)

import anyio
from pydantic import ValidationError

from app.core.config import settings
from app.telemetry.models import TelemetryMessage
from app.telemetry.registry import (
    UnknownSensorError,
    get_registry,
)
from app.telemetry.topics import TopicError, parse_topic


logger = logging.getLogger(__name__)


DEFAULT_BACKOFF_SECONDS = 1.0
DEFAULT_MAX_BACKOFF_SECONDS = 30.0

# Rejection reasons, also used as counter keys.
REASON_TOPIC_MALFORMED = "topic_malformed"
REASON_PAYLOAD_ENCODING = "payload_encoding"
REASON_PAYLOAD_JSON = "payload_json"
REASON_PAYLOAD_NOT_OBJECT = "payload_not_object"
REASON_SCHEMA_INVALID = "schema_invalid"
REASON_SENSOR_MISMATCH = "sensor_mismatch"
REASON_UNKNOWN_SENSOR = "unknown_sensor"
REASON_METRIC_MISMATCH = "metric_mismatch"
REASON_UNIT_MISMATCH = "unit_mismatch"
REASON_LOCATION_MISMATCH = "location_mismatch"

WRITER_ERROR = "writer_error"


@dataclass
class WorkerStats:
    """
    In-memory counters. No metrics endpoint in this stage.
    """

    messages_received: int = 0
    messages_accepted: int = 0
    messages_rejected: int = 0
    writer_errors: int = 0
    connections_established: int = 0
    connection_failures: int = 0
    rejected_by_reason: Dict[str, int] = field(
        default_factory=dict
    )

    def reject(self, reason: str) -> None:
        self.messages_rejected += 1
        self.rejected_by_reason[reason] = (
            self.rejected_by_reason.get(reason, 0) + 1
        )


class MqttTelemetryWorker:
    """
    Subscribes to the campus telemetry topic tree and feeds
    validated readings to a `TelemetryWriter`.
    """

    def __init__(
        self,
        writer,
        registry_loader: Optional[Callable] = None,
        registry=None,
        client_factory: Optional[Callable] = None,
        app_settings: object = None,
        topic_filter: Optional[str] = None,
        reconnect_backoff_seconds: float = (
            DEFAULT_BACKOFF_SECONDS
        ),
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        max_reconnect_attempts: Optional[int] = None,
        qos: int = 0,
    ) -> None:
        self._writer = writer
        self._settings = (
            app_settings if app_settings is not None else settings
        )
        self._registry_loader = (
            registry_loader
            if registry_loader is not None
            else get_registry
        )
        self._registry = registry
        self._client_factory = client_factory
        self._topic_filter_override = topic_filter
        self._backoff = reconnect_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._max_reconnect_attempts = max_reconnect_attempts
        self._qos = qos

        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()
        self.stats = WorkerStats()

    # --- properties ----------------------------------------------

    @property
    def is_running(self) -> bool:
        return (
            self._task is not None and not self._task.done()
        )

    @property
    def registry(self):
        """
        The cached registry, loading it on first access.
        """

        if self._registry is None:
            raise RuntimeError(
                "registry is not loaded yet; the worker loads "
                "it off the event loop on first use"
            )

        return self._registry

    async def load_registry(self):
        """
        Loads the registry once, off the event loop.

        The Supabase client is synchronous, so calling it
        directly on the loop would block every other
        connection on it.
        """

        if self._registry is None:
            self._registry = await anyio.to_thread.run_sync(
                self._registry_loader
            )

            logger.info(
                "Telemetry worker loaded registry with %d "
                "sensors",
                len(self._registry),
            )

        return self._registry

    # --- topic subscription ---------------------------------------

    async def build_topic_filter(self) -> str:
        """
        Builds the narrowest subscription the registry
        supports: one campus, building, floor and zone, with
        `+` for the sensor segment.

        It never becomes `#` or `smart-campus/#`, so unrelated
        traffic on the broker is not delivered.
        """

        if self._topic_filter_override is not None:
            return self._topic_filter_override

        registry = await self.load_registry()

        entry = next(iter(registry))

        return "/".join(
            (
                self._settings.mqtt_topic_prefix,
                "campus",
                entry.campus_code,
                "building",
                entry.building_code,
                "floor",
                entry.floor_code,
                "zone",
                entry.zone_code,
                "sensor",
                "+",
            )
        )

    # --- message handling -----------------------------------------

    async def handle_message(
        self, topic: str, payload: bytes
    ) -> str:
        """
        Validates one message and enqueues it.

        Returns "accepted" or the rejection reason. Never
        raises for bad input; only writer failures are
        swallowed, and those are counted.
        """

        self.stats.messages_received += 1

        # 1. Topic structure.
        try:
            parsed = parse_topic(
                topic,
                prefix=self._settings.mqtt_topic_prefix,
            )
        except TopicError as exc:
            return self._reject(REASON_TOPIC_MALFORMED, topic, exc)

        # 2. Payload bytes -> UTF-8 -> JSON object.
        if isinstance(payload, (bytes, bytearray)):
            try:
                text = bytes(payload).decode("utf-8")
            except UnicodeDecodeError as exc:
                return self._reject(
                    REASON_PAYLOAD_ENCODING, topic, exc
                )
        else:
            text = payload

        try:
            body = json.loads(text)
        except (TypeError, ValueError) as exc:
            return self._reject(REASON_PAYLOAD_JSON, topic, exc)

        if not isinstance(body, dict):
            return self._reject(
                REASON_PAYLOAD_NOT_OBJECT,
                topic,
                f"payload is {type(body).__name__}",
            )

        # 3. Schema.
        try:
            message = TelemetryMessage(**body)
        except ValidationError as exc:
            return self._reject(REASON_SCHEMA_INVALID, topic, exc)

        # 4. The topic and payload must name the same sensor.
        if message.sensor_id != parsed.sensor_id:
            return self._reject(
                REASON_SENSOR_MISMATCH,
                topic,
                "payload sensor "
                f"{message.sensor_id} != topic sensor "
                f"{parsed.sensor_id}",
            )

        # 5. The sensor must be a known one.
        try:
            registry = await self.load_registry()
        except Exception as exc:  # registry unavailable
            logger.error(
                "Telemetry worker could not load the "
                "registry: %s",
                exc,
            )
            self.stats.reject(REASON_UNKNOWN_SENSOR)
            return REASON_UNKNOWN_SENSOR

        try:
            entry = registry.get_by_id(parsed.sensor_id)
        except UnknownSensorError as exc:
            return self._reject(REASON_UNKNOWN_SENSOR, topic, exc)

        # 6. Metric and unit must match the registry.
        if message.metric != entry.metric:
            return self._reject(
                REASON_METRIC_MISMATCH,
                topic,
                f"payload metric '{message.metric}' != "
                f"registry '{entry.metric}'",
            )

        if message.unit != entry.unit:
            return self._reject(
                REASON_UNIT_MISMATCH,
                topic,
                f"payload unit '{message.unit}' != "
                f"registry '{entry.unit}'",
            )

        # 7. Location must agree. Absent values are filled from
        # the registry rather than rejected, so rows are
        # complete without trusting the broker.
        for column, registered in (
            ("campus_id", entry.campus_id),
            ("building_id", entry.building_id),
            ("floor_id", entry.floor_id),
            ("zone_id", entry.zone_id),
        ):
            supplied = getattr(message, column)

            if supplied is not None and supplied != registered:
                return self._reject(
                    REASON_LOCATION_MISMATCH,
                    topic,
                    f"{column} {supplied} != registry "
                    f"{registered}",
                )

        message = self._with_registry_location(
            message, entry
        )

        # 8. Hand over to the writer.
        try:
            await self._writer.enqueue_async(message)
        except Exception as exc:
            # A writer failure must not kill the worker. The
            # writer keeps the rows buffered, so this is
            # logged loudly rather than swallowed.
            self.stats.writer_errors += 1

            logger.exception(
                "Telemetry worker could not enqueue a reading "
                "for sensor %s: %s",
                entry.sensor_code,
                exc,
            )

            return WRITER_ERROR

        self.stats.messages_accepted += 1

        logger.debug(
            "Accepted %s=%s from %s",
            message.metric,
            message.value,
            entry.sensor_code,
        )

        return "accepted"

    @staticmethod
    def _with_registry_location(
        message: TelemetryMessage, entry
    ) -> TelemetryMessage:
        """
        Fills any missing location identifiers from the
        registry, and leaves source, quality and metadata
        untouched: simulated data stays simulated.
        """

        return message.model_copy(
            update={
                "campus_id": message.campus_id
                or entry.campus_id,
                "building_id": message.building_id
                or entry.building_id,
                "floor_id": message.floor_id
                or entry.floor_id,
                "zone_id": message.zone_id
                or entry.zone_id,
                "equipment_id": message.equipment_id
                or entry.equipment_id,
            }
        )

    def _reject(
        self, reason: str, topic: str, detail
    ) -> str:
        self.stats.reject(reason)

        logger.warning(
            "Rejected telemetry message on '%s' [%s]: %s",
            topic,
            reason,
            detail,
        )

        return reason

    # --- lifecycle -----------------------------------------------

    def start(self) -> Optional[asyncio.Task]:
        """
        Starts the worker as a background task.

        Returns None when MQTT is disabled, so nothing
        connects. Nothing is started at import time.
        """

        if not self._settings.mqtt_enabled:
            logger.info(
                "Telemetry worker disabled "
                "(MQTT_ENABLED=false); not connecting"
            )
            return None

        if self.is_running:
            return self._task

        self._stopping.clear()
        self._task = asyncio.create_task(
            self.run(), name="telemetry-mqtt-worker"
        )

        return self._task

    async def stop(self, drain_writer: bool = True) -> None:
        """
        Signals shutdown, waits for the task, and closes the
        writer so buffered readings are drained.
        """

        self._stopping.set()

        task = self._task
        self._task = None

        if task is not None:
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

        if drain_writer:
            try:
                await self._writer.close_async()
            except Exception as exc:
                logger.error(
                    "Telemetry writer did not close cleanly: %s",
                    exc,
                )

    async def __aenter__(self) -> "MqttTelemetryWorker":
        self.start()
        return self

    async def __aexit__(self, *_exc_info) -> None:
        await self.stop()

    def _build_client(self) -> object:
        if self._client_factory is not None:
            return self._client_factory()

        import aiomqtt

        return aiomqtt.Client(
            hostname=self._settings.mqtt_host,
            port=self._settings.mqtt_port,
        )

    async def run(
        self,
        max_messages: Optional[int] = None,
        max_attempts: Optional[int] = None,
    ) -> None:
        """
        Connects, subscribes and consumes messages until
        stopped.

        Connection failures are retried with exponential
        backoff up to `max_backoff_seconds`, so a broker that
        is down does not produce a tight loop.

        `max_messages` and `max_attempts` exist for tests and
        short demos; both are None in normal operation.
        """

        if not self._settings.mqtt_enabled:
            logger.info(
                "Telemetry worker disabled "
                "(MQTT_ENABLED=false); not connecting"
            )
            return

        limit = (
            self._max_reconnect_attempts
            if max_attempts is None
            else max_attempts
        )

        attempt = 0
        consumed = 0

        while not self._stopping.is_set():
            if limit is not None and attempt >= limit:
                logger.info(
                    "Telemetry worker stopping after %d "
                    "connection attempts",
                    attempt,
                )
                return

            attempt += 1

            try:
                consumed = await self._connect_and_consume(
                    max_messages, consumed
                )

                if (
                    max_messages is not None
                    and consumed >= max_messages
                ):
                    logger.info(
                        "Telemetry worker consumed %d messages "
                        "as requested; returning",
                        consumed,
                    )
                    return

                if not self._stopping.is_set():
                    logger.warning(
                        "Telemetry connection closed; "
                        "reconnecting"
                    )

                attempt = 0
            except asyncio.CancelledError:
                logger.info(
                    "Telemetry worker cancelled after %d "
                    "messages",
                    consumed,
                )
                raise
            except Exception as exc:
                self.stats.connection_failures += 1

                logger.warning(
                    "Telemetry connection failed (attempt "
                    "%d): %s",
                    attempt,
                    exc,
                )

                if limit is not None and attempt >= limit:
                    logger.info(
                        "Telemetry worker giving up after %d "
                        "connection attempts",
                        attempt,
                    )
                    return

                delay = min(
                    self._backoff * (2 ** (attempt - 1)),
                    self._max_backoff,
                )

                logger.info(
                    "Retrying telemetry connection in %.1fs",
                    delay,
                )

                if await self._sleep_or_stop(delay):
                    return

    async def _connect_and_consume(
        self,
        max_messages: Optional[int],
        consumed: int = 0,
    ) -> int:
        topic_filter = await self.build_topic_filter()

        client = self._build_client()

        # Entering the context connects; leaving it always
        # disconnects, including on cancellation.
        async with client:
            await client.subscribe(topic_filter, qos=self._qos)

            self.stats.connections_established += 1

            logger.info(
                "Telemetry worker subscribed to '%s' on %s:%s",
                topic_filter,
                self._settings.mqtt_host,
                self._settings.mqtt_port,
            )

            async for message in client.messages:
                await self.handle_message(
                    str(message.topic), message.payload
                )

                consumed += 1

                if (
                    max_messages is not None
                    and consumed >= max_messages
                ):
                    logger.info(
                        "Telemetry worker consumed %d messages "
                        "as requested",
                        consumed,
                    )
                    return consumed

        return consumed

    async def _sleep_or_stop(self, seconds: float) -> bool:
        """
        Waits, returning True early if shutdown was requested.
        """

        try:
            await asyncio.wait_for(
                self._stopping.wait(), timeout=seconds
            )
            return True
        except asyncio.TimeoutError:
            return False