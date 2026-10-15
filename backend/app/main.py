import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.campus import router as campus_router
from app.core.config import settings
from app.telemetry.lifecycle import TelemetryRuntime


logger = logging.getLogger(__name__)


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
        runtime = runtime_factory()

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
    }
