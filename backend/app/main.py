import inspect
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.campus import router as campus_router
from app.api.incidents import router as incidents_router
from app.core.config import settings
from app.services.intelligence_service import (
    intelligence_service,
)
from app.telemetry.lifecycle import TelemetryRuntime


logger = logging.getLogger(__name__)


def _intelligence_observer():
    """
    The intelligence engine, called with each batch of telemetry
    once it is durable.

    Returning the bound method rather than the service keeps the
    telemetry package from importing the intelligence package.
    """

    if not settings.intelligence_enabled:
        return None

    return intelligence_service.process_batch


def _accepts_observer(factory) -> bool:
    """
    Whether `factory` accepts an `observer` keyword.

    Injected runtime factories in the test suite have narrower
    signatures than the real one, so the observer is only passed
    when the factory can actually take it.
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

    return "observer" in parameters


def _build_runtime(runtime_factory):
    observer = _intelligence_observer()

    if observer is not None and _accepts_observer(
        runtime_factory
    ):
        return runtime_factory(observer=observer)

    return runtime_factory()


def create_lifespan(
    runtime_factory=TelemetryRuntime,
):
    """
    Builds the application lifespan.

    `runtime_factory` is injectable so tests can supply a fake
    pipeline. The runtime owns the telemetry writer, the MQTT
    worker and the periodic flush task; shutting down the
    runtime drains buffered readings exactly once.

    A telemetry failure is logged and leaves the API serving
    without telemetry, because a broker outage must not take
    the campus API down with it.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = _build_runtime(runtime_factory)

        app.state.telemetry = runtime

        try:
            await runtime.start()
        except Exception:
            logger.exception(
                "Starting with telemetry unavailable"
            )

        try:
            yield
        finally:
            await runtime.stop()

            app.state.telemetry = None

    return lifespan


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Backend API for the Smart Campus "
        "Digital Twin."
    ),
    lifespan=create_lifespan(),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(campus_router)
app.include_router(incidents_router)


@app.get("/")
def root() -> dict:
    return {
        "application": (
            "Smart Campus Digital Twin"
        ),
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "smart-campus-api",
        "version": settings.app_version,
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "intelligence": intelligence_service.stats,
    }
