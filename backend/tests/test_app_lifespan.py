"""
FastAPI lifespan integration tests.

Offline: fake runtime components, no broker, no Supabase, no
credentials. The real `TelemetryRuntime` is exercised against
fake writer/worker factories and, where useful, a real
`TelemetryWriter` with an injected insert function.

Lifespans are driven through `app.router.lifespan_context`,
which is the supported way to run startup and shutdown without
a server.
"""

import asyncio
from dataclasses import dataclass

import pytest

from app.main import app as production_app
from app.main import create_lifespan
from app.telemetry.lifecycle import TelemetryRuntime
from app.telemetry.models import TelemetryMessage
from app.telemetry.writer import TelemetryWriter


SENSOR_ID = "d1acf785-0000-4000-8000-00000000000a"
ZONE_ID = "26f134ea-0000-4000-8000-000000000004"

# Phase 5C Part 3 added the read-only telemetry route; every
# other route must be exactly as it was.
BASELINE_ROUTES = [
    "/",
    "/api/v1/campus/{campus_code}/telemetry/latest",
    "/api/v1/campus/{campus_code}/twin",
    "/docs",
    "/docs/oauth2-redirect",
    "/health",
    "/openapi.json",
    "/redoc",
]


@dataclass
class FakeSettings:
    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "smart-campus"
    telemetry_tick_seconds: int = 5
    telemetry_flush_seconds: int = 0.01


class RecordingWriter:
    """
    Writer double that records lifecycle calls.
    """

    def __init__(self, app_settings=None) -> None:
        self.flush_interval_seconds = 0.01
        self.flush_calls = 0
        self.run_flusher_calls = 0
        self.close_calls = 0
        self.enqueued = []
        self._flusher_stopped = False

    async def enqueue_async(self, message):
        self.enqueued.append(message)

    async def run_flusher(self, stop=None, max_flushes=None):
        self.run_flusher_calls += 1

        while stop is None or not stop.is_set():
            await asyncio.sleep(0.01)

    async def flush_async(self):
        self.flush_calls += 1

    async def close_async(self, drain: bool = True):
        self.close_calls += 1


class RecordingWorker:
    """
    Worker double that records start/stop and holds a task
    like the real one, so lifecycle behaviour is comparable.
    """

    def __init__(
        self,
        writer=None,
        registry_loader=None,
        app_settings=None,
        client_factory=None,
        start_result="task",
        start_error: Exception = None,
    ) -> None:
        self.writer = writer
        self.registry_loader = registry_loader
        self.app_settings = app_settings
        self.client_factory = client_factory

        self._start_result = start_result
        self._start_error = start_error

        self.start_calls = 0
        self.stop_calls = 0
        self.drain_flags = []
        self.task = None

    def start(self):
        self.start_calls += 1

        if self._start_error is not None:
            raise self._start_error

        if self._start_result is None:
            return None

        async def idle():
            await asyncio.Event().wait()

        self.task = asyncio.create_task(idle())

        return self.task

    async def stop(self, drain_writer: bool = True):
        self.stop_calls += 1
        self.drain_flags.append(drain_writer)

        task = self.task
        self.task = None

        if task is not None:
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

        if drain_writer and self.writer is not None:
            await self.writer.close_async()


def capture_worker(**worker_kwargs):
    """
    Worker factory that builds a worker from the kwargs the
    runtime passes, so it really receives the shared writer,
    and records the instances it built.
    """

    created = []

    def factory(**kwargs):
        worker = RecordingWorker(**worker_kwargs, **kwargs)
        created.append(worker)
        return worker

    return factory, created


def runtime_with(
    enabled: bool = True,
    writer_factory=None,
    worker_factory=None,
    registry_loader=None,
) -> TelemetryRuntime:
    return TelemetryRuntime(
        app_settings=FakeSettings(mqtt_enabled=enabled),
        writer_factory=writer_factory,
        worker_factory=worker_factory,
        registry_loader=registry_loader or (lambda: []),
    )


def make_app(runtime_factory):
    from fastapi import FastAPI

    app = FastAPI(
        title="test",
        lifespan=create_lifespan(runtime_factory),
    )

    @app.get("/")
    def root() -> dict:
        return {"ok": True}

    return app


def run_lifespan(app):
    return app.router.lifespan_context(app)


# --- Routes ------------------------------------------------------


def test_production_routes_are_unchanged():
    assert sorted(
        route.path for route in production_app.routes
    ) == BASELINE_ROUTES


def test_routes_survive_a_full_lifespan():
    runtime = runtime_with(enabled=False)

    app = make_app(lambda: runtime)

    async def scenario():
        async with run_lifespan(app):
            return sorted(
                route.path for route in app.routes
            )

    # The test app adds only "/", on top of FastAPI defaults.
    assert asyncio.run(scenario()) == [
        "/",
        "/docs",
        "/docs/oauth2-redirect",
        "/openapi.json",
        "/redoc",
    ]


# --- Disabled ---------------------------------------------------


def test_disabled_startup_creates_nothing():
    calls = {"writer": 0, "worker": 0, "registry": 0}

    def writer_factory(app_settings=None):
        calls["writer"] += 1
        return RecordingWriter()

    def worker_factory(**kwargs):
        calls["worker"] += 1
        return RecordingWorker(**kwargs)

    def registry_loader():
        calls["registry"] += 1
        return []

    runtime = runtime_with(
        enabled=False,
        writer_factory=writer_factory,
        worker_factory=worker_factory,
        registry_loader=registry_loader,
    )

    app = make_app(lambda: runtime)

    async def scenario():
        async with run_lifespan(app):
            return (
                runtime.started,
                runtime.writer,
                runtime.worker,
                runtime.worker_task,
                runtime.flush_task,
            )

    started, writer, worker, worker_task, flush_task = (
        asyncio.run(scenario())
    )

    assert started is True
    assert writer is None
    assert worker is None
    assert worker_task is None
    assert flush_task is None

    # No connection, no registry query, nothing created.
    assert calls == {
        "writer": 0,
        "worker": 0,
        "registry": 0,
    }


def test_disabled_shutdown_is_a_no_op():
    runtime = runtime_with(enabled=False)

    async def scenario():
        await runtime.start()
        await runtime.stop()
        await runtime.stop()

    asyncio.run(scenario())

    assert runtime.stopped
    assert runtime.writer is None


def test_disabled_app_state_is_set_and_cleared():
    runtime = runtime_with(enabled=False)

    app = make_app(lambda: runtime)

    async def scenario():
        async with run_lifespan(app):
            during = app.state.telemetry

        return during, app.state.telemetry

    during, after = asyncio.run(scenario())

    assert during is runtime
    assert after is None


# --- Enabled -----------------------------------------------------


def test_enabled_startup_creates_resources():
    writer = RecordingWriter()
    factory, workers = capture_worker()

    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: writer,
        worker_factory=factory,
    )

    app = make_app(lambda: runtime)

    async def scenario():
        async with run_lifespan(app):
            # Let the flush task actually begin running.
            await asyncio.sleep(0.02)

            return (
                runtime.started,
                runtime.writer,
                runtime.worker,
                runtime.worker_task is not None,
                runtime.flush_task is not None,
                runtime.is_connected,
                len(workers),
            )

    (
        started,
        created_writer,
        created_worker,
        has_worker_task,
        has_flush_task,
        connected,
        worker_count,
    ) = asyncio.run(scenario())

    assert started
    assert created_writer is writer
    assert created_worker is workers[0]
    # The worker received the very same writer instance.
    assert workers[0].writer is writer
    assert has_worker_task
    assert has_flush_task
    assert connected
    assert worker_count == 1
    assert writer.run_flusher_calls == 1


def test_startup_starts_exactly_one_worker():
    writer = RecordingWriter()
    factory, workers = capture_worker()

    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: writer,
        worker_factory=factory,
    )

    async def scenario():
        await runtime.start()
        await runtime.start()  # must not duplicate

        await runtime.stop()

    asyncio.run(scenario())

    assert len(workers) == 1
    assert workers[0].start_calls == 1


def test_writer_and_worker_receive_shared_settings():
    seen = {}

    def writer_factory(app_settings=None):
        seen["writer_settings"] = app_settings
        return RecordingWriter()

    def worker_factory(**kwargs):
        seen["worker_settings"] = kwargs.get("app_settings")
        seen["writer"] = kwargs.get("writer")
        seen["registry_loader"] = kwargs.get("registry_loader")
        seen["client_factory"] = kwargs.get("client_factory")
        return RecordingWorker(**kwargs)

    def registry_loader():
        return []

    def client_factory():
        return None

    runtime = runtime_with(
        enabled=True,
        writer_factory=writer_factory,
        worker_factory=worker_factory,
        registry_loader=registry_loader,
    )
    runtime._client_factory = client_factory

    async def scenario():
        await runtime.start()
        await runtime.stop()

    asyncio.run(scenario())

    # One settings object and one registry loader shared by
    # both components, and the same writer instance, not a
    # second one.
    assert seen["writer_settings"] is seen["worker_settings"]
    assert seen["registry_loader"] is registry_loader
    assert seen["client_factory"] is client_factory


def test_shutdown_stops_the_worker_and_awaits_it():
    writer = RecordingWriter()
    factory, workers = capture_worker()

    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: writer,
        worker_factory=factory,
    )

    async def scenario():
        await runtime.start()
        task = runtime.worker_task

        await runtime.stop()

        return task

    task = asyncio.run(scenario())

    assert workers[0].stop_calls == 1
    assert task.done()
    assert task.cancelled()


def test_shutdown_cancels_the_flush_task():
    writer = RecordingWriter()
    factory, _workers = capture_worker()

    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: writer,
        worker_factory=factory,
    )

    async def scenario():
        await runtime.start()
        flush_task = runtime.flush_task

        await runtime.stop()

        return flush_task

    flush_task = asyncio.run(scenario())

    assert flush_task.done()


def test_flush_task_stops_before_the_worker():
    """
    Order matters: the periodic flush must be cancelled before
    the writer is closed, or it could write to a closed writer.
    """

    events = []

    class OrderedWriter(RecordingWriter):
        async def run_flusher(self, stop=None, max_flushes=None):
            try:
                while stop is None or not stop.is_set():
                    await asyncio.sleep(0.005)
            except asyncio.CancelledError:
                # Cancellation, not the stop event, is what
                # ends this loop.
                events.append("flusher-stopped")
                raise

            events.append("flusher-stopped")

    class OrderedWorker(RecordingWorker):
        async def stop(self, drain_writer: bool = True):
            events.append("worker-stopped")
            await super().stop(drain_writer)

    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: OrderedWriter(),
        worker_factory=lambda **kwargs: OrderedWorker(**kwargs),
    )

    async def scenario():
        await runtime.start()
        # Let the flush task actually start before shutdown.
        await asyncio.sleep(0.02)
        await runtime.stop()

    asyncio.run(scenario())

    assert events == ["flusher-stopped", "worker-stopped"]


def test_shutdown_drains_the_writer_exactly_once():
    writer = RecordingWriter()
    factory, workers = capture_worker()

    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: writer,
        worker_factory=factory,
    )

    async def scenario():
        await runtime.start()
        await runtime.stop()
        await runtime.stop()

    asyncio.run(scenario())

    # The worker owns the writer close; the runtime does not
    # add a second path.
    assert writer.close_calls == 1
    assert workers[0].drain_flags == [True]


# --- Real writer, drained once -----------------------------------


def real_writer_factory(insert_rows):
    def factory(**kwargs):
        return TelemetryWriter(
            insert_fn=insert_rows.append,
            flush_interval_seconds=0.01,
            **kwargs,
        )

    return factory


def test_buffered_readings_are_written_once_on_shutdown():
    inserted = []

    writer = TelemetryWriter(
        insert_fn=inserted.append,
        flush_interval_seconds=60,  # never fires on its own
    )

    class RealishWorker:
        def __init__(self, writer, **kwargs):
            self.writer = writer
            self.task = None

        def start(self):
            async def idle():
                await asyncio.Event().wait()

            self.task = asyncio.create_task(idle())

            return self.task

        async def stop(self, drain_writer: bool = True):
            task = self.task
            self.task = None

            if task is not None:
                task.cancel()

                try:
                    await task
                except asyncio.CancelledError:
                    pass

            await self.writer.close_async()

    runtime = TelemetryRuntime(
        app_settings=FakeSettings(mqtt_enabled=True),
        writer_factory=lambda **kwargs: writer,
        worker_factory=lambda writer, **kwargs: RealishWorker(
            writer, **kwargs
        ),
        registry_loader=lambda: [],
    )

    async def scenario():
        await runtime.start()

        # Simulate readings arriving, far below the buffer
        # bound so nothing forces a flush.
        for index in range(3):
            await writer.enqueue_async(
                TelemetryMessage(
                    sensor_id=SENSOR_ID,
                    metric="temperature",
                    value=20.0 + index,
                    unit="°C",
                    timestamp=__import__(
                        "datetime"
                    ).datetime.now(
                        __import__("datetime").timezone.utc
                    ),
                    source="simulator",
                    quality="good",
                    zone_id=ZONE_ID,
                )
            )

        assert writer.buffer_size == 3

        await runtime.stop()

        return runtime

    asyncio.run(scenario())

    rows = [row for batch in inserted for row in batch]

    assert len(rows) == 3
    assert writer.buffer_size == 0
    assert writer.is_closed


# --- Partial startup failure --------------------------------------


def test_partial_startup_failure_cleans_up():
    writer = RecordingWriter()
    factory, workers = capture_worker(
        start_error=RuntimeError("broker refused")
    )

    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: writer,
        worker_factory=factory,
    )

    async def scenario():
        with pytest.raises(RuntimeError):
            await runtime.start()

    asyncio.run(scenario())

    assert workers[0].start_calls == 1

    # Writer closed exactly once through the worker, and the
    # runtime holds no resources afterwards.
    assert writer.close_calls == 1
    assert runtime.writer is None
    assert runtime.worker is None
    assert runtime.worker_task is None
    assert runtime.flush_task is None


def test_worker_refusing_to_start_is_treated_as_failure():
    writer = RecordingWriter()
    factory, workers = capture_worker(start_result=None)

    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: writer,
        worker_factory=factory,
    )

    async def scenario():
        with pytest.raises(RuntimeError):
            await runtime.start()

    asyncio.run(scenario())

    # A worker that never took the writer still gets it closed,
    # so no buffered data could be orphaned.
    assert writer.close_calls == 1
    assert runtime.started is False


def test_writer_factory_failure_propagates():
    def boom(**kwargs):
        raise RuntimeError("cannot build writer")

    runtime = runtime_with(
        enabled=True, writer_factory=boom
    )

    async def scenario():
        with pytest.raises(RuntimeError):
            await runtime.start()

    asyncio.run(scenario())

    assert runtime.writer is None
    assert runtime.worker is None


def test_lifespan_survives_a_startup_failure():
    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("cannot build writer")
        ),
    )

    app = make_app(lambda: runtime)

    async def scenario():
        async with run_lifespan(app):
            # The API still serves without telemetry.
            return app.state.telemetry is runtime

    assert asyncio.run(scenario()) is True


# --- Repeated lifespans -------------------------------------------


def test_repeated_lifespans_do_not_leak_tasks():
    created = []

    def worker_factory(**kwargs):
        worker = RecordingWorker(**kwargs)
        created.append(worker)
        return worker

    async def scenario():
        before = len(asyncio.all_tasks())

        for _ in range(3):
            runtime = runtime_with(
                enabled=True,
                writer_factory=lambda **kw: RecordingWriter(),
                worker_factory=worker_factory,
            )

            app = make_app(lambda runtime=runtime: runtime)

            async with run_lifespan(app):
                assert runtime.is_connected

            assert not runtime.is_connected

        await asyncio.sleep(0.05)

        return before, len(asyncio.all_tasks())

    before, after = asyncio.run(scenario())

    assert len(created) == 3
    assert worker_start_counts(created) == [1, 1, 1]
    assert after <= before


def worker_start_counts(workers):
    return [worker.start_calls for worker in workers]


def test_repeated_stop_does_not_drain_twice():
    writer = RecordingWriter()
    factory, workers = capture_worker()

    runtime = runtime_with(
        enabled=True,
        writer_factory=lambda **kwargs: writer,
        worker_factory=factory,
    )

    async def scenario():
        await runtime.start()
        await runtime.stop()
        await runtime.stop()
        await runtime.stop()

    asyncio.run(scenario())

    assert writer.close_calls == 1
    assert workers[0].stop_calls == 1


def test_runtime_can_be_restarted_after_stop():
    writers = []
    workers = []

    def writer_factory(**kwargs):
        writer = RecordingWriter()
        writers.append(writer)
        return writer

    def worker_factory(**kwargs):
        worker = RecordingWorker(**kwargs)
        workers.append(worker)
        return worker

    runtime = runtime_with(
        enabled=True,
        writer_factory=writer_factory,
        worker_factory=worker_factory,
    )

    async def scenario():
        await runtime.start()
        await runtime.stop()

        await runtime.start()
        await runtime.stop()

    asyncio.run(scenario())

    # A fresh writer and worker per cycle, no reuse of closed
    # resources.
    assert len(writers) == 2
    assert len(workers) == 2
    assert workers[0].start_calls == 1
    assert workers[1].start_calls == 1


def test_disabled_then_enabled_runtime_reports_correctly():
    runtime = runtime_with(enabled=False)

    async def scenario():
        await runtime.start()
        disabled_state = runtime.is_connected
        await runtime.stop()

        return disabled_state

    assert asyncio.run(scenario()) is False
    assert runtime.enabled is False


# --- Import safety -------------------------------------------------


def test_importing_the_app_starts_nothing():
    """
    Importing app.main must not connect, load the registry or
    create tasks.
    """

    import importlib

    import app.telemetry.lifecycle as lifecycle_module

    before_threads = __import__("threading").active_count()

    importlib.reload(lifecycle_module)

    app_module = importlib.import_module("app.main")

    assert (
        __import__("threading").active_count()
        == before_threads
    )
    assert not hasattr(app_module.app.state, "telemetry")

    assert sorted(
        route.path for route in app_module.app.routes
    ) == BASELINE_ROUTES


def test_worker_task_is_not_created_when_disabled():
    runtime = runtime_with(enabled=False)

    async def scenario():
        await runtime.start()

        return runtime.worker_task, runtime.flush_task

    worker_task, flush_task = asyncio.run(scenario())

    assert worker_task is None
    assert flush_task is None