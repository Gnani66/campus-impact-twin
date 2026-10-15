"""
Application lifecycle for the telemetry pipeline.

`TelemetryRuntime` is created per application, started in the
FastAPI lifespan and stopped on shutdown.

Resource ownership, so nothing is closed twice:

    TelemetryRuntime
      |-- owns the periodic flush task
      `-- owns MqttTelemetryWorker
                `-- owns TelemetryWriter

The worker's `stop()` already closes the writer it was given,
so this module never closes the writer itself. Shutdown order
is: cancel the flush task first, then stop the worker, which
drains buffered readings exactly once.

When `MQTT_ENABLED` is false nothing is created at all: no
writer, no worker, no registry load and no connection. The API
behaves exactly as it did before telemetry existed.

Nothing here runs at import time.
"""

import asyncio
import inspect
import logging
from typing import (
    Any,
    Callable,
    Dict,
    Optional,
)

from app.core.config import settings
from app.telemetry.mqtt_worker import MqttTelemetryWorker
from app.telemetry.registry import get_registry
from app.telemetry.writer import TelemetryWriter


logger = logging.getLogger(__name__)


class TelemetryRuntime:
    """
    Owns the writer, the MQTT worker and the periodic flush
    task for one application instance.
    """

    def __init__(
        self,
        app_settings: object = None,
        writer_factory: Optional[Callable] = None,
        worker_factory: Optional[Callable] = None,
        registry_loader: Optional[Callable] = None,
        observer: Optional[Callable] = None,
        client_factory: Optional[Callable] = None,
    ) -> None:
        self._settings = (
            app_settings if app_settings is not None else settings
        )
        self._writer_factory = writer_factory or TelemetryWriter
        self._worker_factory = (
            worker_factory or MqttTelemetryWorker
        )
        self._registry_loader = registry_loader or get_registry
        self._client_factory = client_factory

        # Called with each batch of rows once they are durable.
        # Wired to the intelligence engine by the application, so
        # the telemetry package does not import it directly.
        self._observer = observer

        self._writer = None
        self._worker = None
        self._flush_task = None
        self._flush_stop = None
        self._worker_task = None
        self._started = False
        self._stopped = False

    # --- state ----------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self._settings.mqtt_enabled)

    @property
    def started(self) -> bool:
        return self._started

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def writer(self):
        return self._writer

    @property
    def worker(self):
        return self._worker

    @property
    def worker_task(self):
        """
        The worker's own task, once started. `None` when MQTT
        is disabled, because no task is created.
        """

        return self._worker_task

    @property
    def flush_task(self):
        return self._flush_task

    @property
    def is_connected(self) -> bool:
        """
        True while the worker holds a live worker task. Useful
        for health reporting; a reconnect inside a running task
        does not change it.
        """

        return (
            self._worker_task is not None
            and not self._worker_task.done()
        )

    # --- startup --------------------------------------------------

    def _build_writer(self):
        """
        Builds the writer, attaching the intelligence engine when
        both are enabled and the factory supports it.

        The observer is passed as a keyword argument only if the
        factory can accept it, so existing injected factories with
        narrower signatures keep working.
        """

        kwargs: Dict[str, Any] = {
            "app_settings": self._settings
        }

        if (
            self._observer is not None
            and self._accepts_observer(self._writer_factory)
        ):
            kwargs["on_persisted"] = self._observer

        return self._writer_factory(**kwargs)

    @staticmethod
    def _accepts_observer(factory) -> bool:
        """
        Whether `factory` accepts an `on_persisted` keyword.
        """

        try:
            parameters = inspect.signature(factory).parameters
        except (TypeError, ValueError):
            return False

        if any(
            parameter.kind
            is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return True

        return "on_persisted" in parameters

    async def start(self) -> None:
        """
        Brings the pipeline up.

        All or nothing: if any step fails, everything created
        so far is cleaned up before the error propagates.
        """

        if self._started:
            # A second start must not duplicate the worker.
            logger.warning(
                "Telemetry runtime already started; ignoring"
            )
            return

        if not self.enabled:
            logger.info(
                "MQTT_ENABLED=false; telemetry pipeline "
                "not started"
            )
            self._started = True
            self._stopped = False
            return

        self._flush_stop = asyncio.Event()

        try:
            self._writer = self._build_writer()

            self._worker = self._worker_factory(
                writer=self._writer,
                registry_loader=self._registry_loader,
                app_settings=self._settings,
                client_factory=self._client_factory,
            )

            # Returns None when the worker decides not to
            # connect, which is the disabled case handled above.
            self._worker_task = self._worker.start()

            if self._worker_task is None:
                raise RuntimeError(
                    "telemetry worker refused to start while "
                    "MQTT_ENABLED is true"
                )

            # The writer's own periodic flush, off the event
            # loop inside the writer itself.
            self._flush_task = asyncio.create_task(
                self._writer.run_flusher(
                    stop=self._flush_stop
                ),
                name="telemetry-flush",
            )

            self._started = True
            self._stopped = False

            logger.info(
                "Telemetry pipeline started: worker and "
                "periodic flush every %ss",
                getattr(
                    self._writer,
                    "flush_interval_seconds",
                    "unknown",
                ),
            )

        except Exception as exc:
            logger.exception(
                "Telemetry pipeline failed to start: %s", exc
            )

            await self._cleanup_failed_start()

            raise

    async def _cleanup_failed_start(self) -> None:
        """
        Releases anything created before the failure.

        The writer is closed through the worker, because that is
        the ownership contract; there is no second close path.
        """

        self._stopped = True

        await self._stop_flush_task()

        worker = self._worker
        self._worker = None
        self._worker_task = None

        if worker is not None:
            try:
                await worker.stop()
            except Exception as exc:
                logger.error(
                    "Telemetry worker cleanup failed: %s", exc
                )

        self._writer = None

    # --- shutdown -------------------------------------------------

    async def stop(self) -> None:
        """
        Shuts the pipeline down. Idempotent, so a repeated
        shutdown cannot drain the writer twice.
        """

        if self._stopped:
            return

        self._stopped = True
        self._started = False

        await self._stop_flush_task()

        worker = self._worker
        self._worker = None
        self._worker_task = None

        if worker is not None:
            try:
                # Cancels the worker task, awaits it, then
                # closes the writer with a final drain.
                await worker.stop()
            except Exception as exc:
                logger.error(
                    "Telemetry worker did not stop cleanly: %s",
                    exc,
                )

        self._writer = None

        logger.info("Telemetry pipeline stopped")

    async def _stop_flush_task(self) -> None:
        task = self._flush_task
        stop_event = self._flush_stop

        self._flush_task = None
        self._flush_stop = None

        if task is not None:
            if stop_event is not None:
                stop_event.set()

            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error(
                    "Periodic telemetry flush did not stop "
                    "cleanly: %s",
                    exc,
                )