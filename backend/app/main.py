import inspect
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.campus import router as campus_router
from app.api.correlation import router as correlation_router
from app.api.impact import router as impact_router
from app.api.incidents import router as incidents_router
from app.api.interventions import (
    router as interventions_router,
)
from app.api.simulation import router as simulation_router
from app.core.config import settings
from app.services.intelligence_service import (
    intelligence_service,
)
from app.telemetry.lifecycle import TelemetryRuntime


logger = logging.getLogger(__name__)


def include_vision_router(application: FastAPI) -> bool:
    """
    Registers the Phase 7 vision routes, if they should be
    served and can be defined.

    Two independent conditions gate the feature:

    * `VISION_ENABLED` — the operator's switch. When false the
      router is never imported, so no vision endpoint exists to
      run inference or touch the database. This is the kill
      switch for the whole Phase 7 feature.
    * `python-multipart` — FastAPI refuses to define a route
      that takes a file upload without it, and raises while the
      route is being declared rather than while it is called.
      Importing the router eagerly would therefore stop the
      whole API from starting.

    A development checkout that has not installed the optional
    vision extras should still serve the campus and incident
    endpoints, so a missing dependency is logged and the rest
    of the API comes up without the vision routes. The same
    trade-off the lifespan already makes for a telemetry
    outage: a degraded feature must not take the campus API
    down with it.

    Returns whether the routes were registered.
    """

    if not settings.vision_enabled:
        logger.warning(
            "Vision routes not registered: "
            "VISION_ENABLED is false. The vision API is "
            "disabled and will not run inference or write "
            "observations."
        )
        return False

    try:
        from app.api.vision import (
            router as vision_router,
        )
    except RuntimeError as exc:
        logger.warning(
            "Vision routes not registered: %s. Install "
            "python-multipart to enable them.",
            exc,
        )
        return False

    application.include_router(vision_router)

    logger.info("Vision routes registered")

    return True


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

# The correlation engine reads stored observations, so it is
# always registered. It is not gated behind VISION_ENABLED: a
# zone whose last camera reading is weeks old is still a zone
# the gate should judge and downgrade, and hiding the endpoint
# would make that silence indistinguishable from a fault.
app.include_router(correlation_router)

VISION_ROUTES_ENABLED = include_vision_router(app)

# Phase 9 and 10. Neither router actuates anything: they model
# and compare, and applying an intervention is a later,
# human-approved step. Registered unconditionally so a client
# can always ask what the system would do and be told.
app.include_router(interventions_router)
app.include_router(impact_router)
app.include_router(simulation_router)


def vision_health() -> dict:
    """
    Reports whether the vision API can actually be called.

    A disabled feature, or a missing dependency, must never be
    mistaken for a working vision engine, so the state is
    published on `/health` rather than only logged at startup.

    `enabled` is the operator's switch, `routes_registered`
    is false when `/api/v1/vision/*` answers 404, and
    `detector_available` is false when the model weights are
    absent. All three being true is the only state in which
    the vision API is usable.
    """

    report = {
        "enabled": settings.vision_enabled,
        "routes_registered": VISION_ROUTES_ENABLED,
        "detector_available": False,
    }

    if not settings.vision_enabled:
        report["detail"] = (
            "Vision is disabled by VISION_ENABLED=false. No "
            "vision route is registered, so no inference "
            "runs and no observation is written."
        )
        return report

    if not VISION_ROUTES_ENABLED:
        report["detail"] = (
            "Vision routes are not registered. Install the "
            "backend requirements; POST /api/v1/vision/analyze "
            "will return 404 until then."
        )
        return report

    try:
        from app.services.vision_service import (
            vision_service,
        )

        report["detector_available"] = (
            vision_service.is_available()
        )
        report["model_name"] = (
            vision_service.detector.model_name
        )
    except Exception:
        report["detail"] = (
            "Vision service could not be inspected"
        )

    return report


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
        "vision": vision_health(),
    }
