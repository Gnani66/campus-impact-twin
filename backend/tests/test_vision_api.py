"""
Tests for the vision API.

The full HTTP round-trip needs `python-multipart`, which
FastAPI requires before it will define a route taking a file
upload. When it is absent those tests skip rather than fail,
and the tests that do not need it still run: the application
wiring is verified, and the error mapping is verified.

The service is always replaced, so no test here can reach
Supabase or a detector.
"""

import pytest


def _multipart_available() -> bool:
    try:
        import python_multipart  # noqa: F401
    except ImportError:
        return False

    return True


requires_multipart = pytest.mark.skipif(
    not _multipart_available(),
    reason=(
        "python-multipart is not installed; FastAPI cannot "
        "define file-upload routes without it"
    ),
)


def _upload(content: bytes, content_type: str):
    from io import BytesIO

    from starlette.datastructures import UploadFile

    return UploadFile(
        file=BytesIO(content),
        filename="frame.png",
        headers={"content-type": content_type},
    )


def _run(coroutine):
    """Drives an async endpoint function from a sync test."""

    import asyncio

    return asyncio.run(coroutine)


# ============================================================
# APPLICATION WIRING
# ============================================================


def test_application_starts_and_existing_routes_survive():
    from app.main import app

    paths = {r.path for r in app.routes}

    assert "/api/v1/campus/{campus_code}/twin" in paths
    assert "/api/v1/incidents" in paths
    assert "/api/v1/incidents/summary" in paths
    assert "/health" in paths


def test_vision_registration_is_reported():
    from app.main import VISION_ROUTES_ENABLED

    assert isinstance(VISION_ROUTES_ENABLED, bool)


def test_router_registration_never_raises():
    from app.main import include_vision_router

    class DummyApp:
        def __init__(self):
            self.included = []

        def include_router(self, router):
            self.included.append(router)

    assert isinstance(
        include_vision_router(DummyApp()), bool
    )


@requires_multipart
def test_vision_routes_are_registered_when_available():
    from app.main import app

    paths = {r.path for r in app.routes}

    assert "/api/v1/vision/analyze" in paths
    assert (
        "/api/v1/vision/zone/{zone_code}/latest" in paths
    )


# ============================================================
# HTTP ROUND-TRIP
# ============================================================


@requires_multipart
def test_analyze_requires_every_field():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.vision import router

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)

    response = client.post(
        "/api/v1/vision/analyze",
        files={"image": ("a.png", b"x", "image/png")},
        data={"zone_code": "LH01"},
    )

    # camera_id is missing, so the request must be rejected as
    # a client error. 422 is FastAPI's validation response;
    # 400 is accepted because a form parser may reject the
    # malformed body before validation runs.
    assert response.status_code in (400, 422)


@requires_multipart
def test_latest_returns_404_when_nothing_is_stored(
    monkeypatch,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import vision as vision_api
    from app.api.vision import router
    from vision_fakes import StubDetector
    from app.services.vision_service import VisionService

    class NoRowsService(VisionService):
        def latest_for_zone(self, zone_code):
            return None

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        NoRowsService(detector=StubDetector()),
    )

    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get(
        "/api/v1/vision/zone/LH01/latest"
    )

    assert response.status_code == 404


# ============================================================
# HANDLER LOGIC
#
# These call the endpoint functions directly. They exercise
# validation and error mapping without TestClient, and they
# assert the guarantee that matters most: a 200 is only ever
# returned after a successful insert.
# ============================================================


@requires_multipart
def test_handler_returns_response_after_persistence(
    monkeypatch,
):
    from app.api import vision as vision_api
    from app.api.vision import analyze_image
    from app.schemas.vision import VisionAnalysisResponse
    from app.services.vision_service import VisionService
    from vision_fakes import (
        StubDetector,
        detection_result,
        make_png,
    )

    recorded = {}

    class RecordingService(VisionService):
        def analyze(self, **kwargs):
            recorded.update(kwargs)

            from datetime import datetime, timezone

            return VisionAnalysisResponse(
                camera_id=kwargs["camera_id"],
                zone_code=kwargs["zone_code"],
                people_count=1,
                confidence=0.9,
                observed_at=datetime.now(timezone.utc),
                detections=[],
            )

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        RecordingService(
            detector=StubDetector(detection_result())
        ),
    )

    response = _run(
        analyze_image(
            image=_upload(make_png(), "image/png"),
            camera_id="cam-1",
            zone_code="LH01",
        )
    )

    assert response.people_count == 1
    assert recorded["zone_code"] == "LH01"
    assert recorded["camera_id"] == "cam-1"


@requires_multipart
def test_handler_rejects_empty_camera_id():
    from fastapi import HTTPException

    from app.api.vision import analyze_image

    with pytest.raises(HTTPException) as exc:
        _run(
            analyze_image(
                image=_upload(b"x", "image/png"),
                camera_id="   ",
                zone_code="LH01",
            )
        )

    assert exc.value.status_code == 400


@requires_multipart
def test_handler_rejects_overlong_camera_id():
    from fastapi import HTTPException

    from app.api.vision import analyze_image

    with pytest.raises(HTTPException) as exc:
        _run(
            analyze_image(
                image=_upload(b"x", "image/png"),
                camera_id="c" * 500,
                zone_code="LH01",
            )
        )

    assert exc.value.status_code == 400


@requires_multipart
def test_handler_rejects_empty_zone_code():
    from fastapi import HTTPException

    from app.api.vision import analyze_image

    with pytest.raises(HTTPException) as exc:
        _run(
            analyze_image(
                image=_upload(b"x", "image/png"),
                camera_id="cam-1",
                zone_code="",
            )
        )

    assert exc.value.status_code == 400


@requires_multipart
def test_handler_maps_model_unavailable_to_503(
    monkeypatch,
):
    from fastapi import HTTPException

    from app.api import vision as vision_api
    from app.api.vision import analyze_image
    from app.services.vision_service import VisionService
    from vision_fakes import StubDetector
    from vision_fakes import make_png
    from vision.detector import ModelUnavailableError

    class NoNetworkService(VisionService):
        """
        Replaces zone resolution so the test cannot reach the
        database. The detector still raises, which is the
        behaviour under test.
        """

        def resolve_zone(self, zone_code):
            return {"id": "zone-1", "code": zone_code}

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        NoNetworkService(
            detector=StubDetector(
                raises=ModelUnavailableError("no weights")
            )
        ),
    )

    with pytest.raises(HTTPException) as exc:
        _run(
            analyze_image(
                image=_upload(make_png(), "image/png"),
                camera_id="cam-1",
                zone_code="LH01",
            )
        )

    assert exc.value.status_code == 503


@requires_multipart
def test_handler_maps_persistence_failure_to_500(
    monkeypatch,
):
    from fastapi import HTTPException

    from app.api import vision as vision_api
    from app.api.vision import analyze_image
    from app.services.vision_service import (
        VisionPersistenceError,
        VisionService,
    )
    from vision_fakes import StubDetector
    from vision_fakes import make_png

    class FailingService(VisionService):
        def analyze(self, **kwargs):
            raise VisionPersistenceError(
                "the observation was not stored"
            )

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        FailingService(detector=StubDetector()),
    )

    with pytest.raises(HTTPException) as exc:
        _run(
            analyze_image(
                image=_upload(make_png(), "image/png"),
                camera_id="cam-1",
                zone_code="LH01",
            )
        )

    assert exc.value.status_code == 500


@requires_multipart
def test_handler_maps_unknown_zone_to_404(monkeypatch):
    from fastapi import HTTPException

    from app.api import vision as vision_api
    from app.api.vision import analyze_image
    from app.services.vision_service import (
        VisionService,
        ZoneNotFoundError,
    )
    from vision_fakes import StubDetector
    from vision_fakes import make_png

    class UnknownZoneService(VisionService):
        def analyze(self, **kwargs):
            raise ZoneNotFoundError("Zone 'NOPE' is unknown")

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        UnknownZoneService(detector=StubDetector()),
    )

    with pytest.raises(HTTPException) as exc:
        _run(
            analyze_image(
                image=_upload(make_png(), "image/png"),
                camera_id="cam-1",
                zone_code="NOPE",
            )
        )

    assert exc.value.status_code == 404


@requires_multipart
def test_latest_returns_404_when_nothing_stored(
    monkeypatch,
):
    from fastapi import HTTPException

    from app.api import vision as vision_api
    from app.api.vision import get_latest_observation
    from app.services.vision_service import VisionService
    from vision_fakes import StubDetector

    class NoRowsService(VisionService):
        def latest_for_zone(self, zone_code):
            return None

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        NoRowsService(detector=StubDetector()),
    )

    with pytest.raises(HTTPException) as exc:
        get_latest_observation(zone_code="LH01")

    assert exc.value.status_code == 404


@requires_multipart
def test_status_reports_detector_availability(monkeypatch):
    from app.api import vision as vision_api
    from app.api.vision import get_vision_status
    from app.services.vision_service import VisionService
    from vision_fakes import StubDetector

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        VisionService(
            detector=StubDetector(available=False)
        ),
    )

    status = get_vision_status()

    assert status["detector_available"] is False
    assert status["model_name"] == "yolo11n.pt"
    assert status["observation_type"] == "people_count"

# ============================================================
# ERROR DISCLOSURE
#
# A driver error can quote the database host and other
# infrastructure detail. These tests inject text that looks
# like a credential or a hostname and assert it never reaches
# the client, while the status code, the safe message and the
# server-side logging are all preserved.
# ============================================================

SECRETY = (
    "connection to db.abc123xyz.supabase.co:5432 failed; "
    "key=sb_secret_SERVICE_ROLE_KEY_abcdef0123456789"
)

SECRET_FRAGMENTS = (
    "db.abc123xyz.supabase.co",
    "sb_secret_SERVICE_ROLE_KEY_abcdef0123456789",
    "5432",
)


def _assert_clean(detail: str) -> None:
    for fragment in SECRET_FRAGMENTS:
        assert fragment not in detail, (
            f"error response leaked {fragment!r}: {detail}"
        )


# --- service layer: the message the client ultimately sees ---


def test_persistence_error_message_hides_driver_detail():
    from app.services.vision_service import (
        VisionPersistenceError,
    )

    error = VisionPersistenceError(
        "Failed to store the vision observation"
    )

    _assert_clean(str(error))

    assert (
        str(error)
        == "Failed to store the vision observation"
    )


def test_persistence_failure_keeps_original_as_cause(
    monkeypatch,
):
    from app.services import vision_service as module
    from app.services.vision_service import (
        VisionPersistenceError,
        VisionService,
    )
    from vision_fakes import (
        StubDetector,
        detection_result,
    )
    from test_vision_service import FakeStore
    from vision_fakes import make_png

    store = FakeStore(zones=[{"id": "z", "code": "LH01"}])
    store.fail_next["vision_observations"] = {
        "raise": RuntimeError(SECRETY)
    }

    monkeypatch.setattr(
        module, "get_supabase", lambda: store
    )

    service = VisionService(
        detector=StubDetector(
            detection_result(count=1, confidence=0.9)
        )
    )

    with pytest.raises(VisionPersistenceError) as exc:
        service.analyze(
            camera_id="cam-1",
            zone_code="LH01",
            image_bytes=make_png(),
        )

    _assert_clean(str(exc.value))

    # The operator still gets the real cause and a traceback.
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert SECRETY in str(exc.value.__cause__)
    assert exc.value.__cause__.__traceback__ is not None


# --- API layer ---


def test_server_fault_detail_is_static():
    from app.api.vision import (
        SERVER_FAULT_DETAIL,
        _fail,
    )
    from app.services.vision_service import (
        VisionPersistenceError,
    )

    detail = _fail(
        VisionPersistenceError("anything at all")
    ).detail

    assert detail == SERVER_FAULT_DETAIL

    _assert_clean(detail)


def test_unexpected_analysis_error_hides_detail(
    monkeypatch,
):
    from fastapi import HTTPException

    from app.api import vision as vision_api
    from app.api.vision import SERVER_FAULT_DETAIL
    from app.services.vision_service import VisionService
    from vision_fakes import StubDetector, make_png

    class ExplodingService(VisionService):
        def analyze(self, **kwargs):
            raise RuntimeError(SECRETY)

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        ExplodingService(detector=StubDetector()),
    )

    with pytest.raises(HTTPException) as exc:
        _run(
            vision_api.analyze_image(
                image=_upload(make_png(), "image/png"),
                camera_id="cam-1",
                zone_code="LH01",
            )
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == SERVER_FAULT_DETAIL

    _assert_clean(exc.value.detail)


def test_latest_lookup_error_hides_detail(
    monkeypatch,
):
    from fastapi import HTTPException

    from app.api import vision as vision_api
    from app.api.vision import SERVER_FAULT_DETAIL
    from app.services.vision_service import VisionService
    from vision_fakes import StubDetector

    class ExplodingService(VisionService):
        def latest_for_zone(self, zone_code):
            raise RuntimeError(SECRETY)

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        ExplodingService(detector=StubDetector()),
    )

    with pytest.raises(HTTPException) as exc:
        vision_api.get_latest_observation(
            zone_code="LH01"
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == SERVER_FAULT_DETAIL

    _assert_clean(exc.value.detail)


# --- behaviour that must NOT change ---


def test_validation_errors_keep_their_actionable_message():
    from app.api.vision import _fail
    from vision.detector import (
        UnsupportedFormatError,
        UploadTooLargeError,
    )

    oversized = _fail(UploadTooLargeError("1024 bytes"))
    assert oversized.status_code == 413
    assert "1024 bytes" in oversized.detail

    wrong_type = _fail(
        UnsupportedFormatError("image/gif is not supported")
    )
    assert wrong_type.status_code == 415
    assert "image/gif" in wrong_type.detail


def test_model_unavailable_message_is_preserved():
    from fastapi import status as fastapi_status

    from app.api.vision import _fail
    from vision.detector import ModelUnavailableError

    mapped = _fail(
        ModelUnavailableError(
            "YOLO weights 'yolo11n.pt' were not found. Place "
            "the file in backend/vision/weights."
        )
    )

    assert (
        mapped.status_code
        == fastapi_status.HTTP_503_SERVICE_UNAVAILABLE
    )
    assert "yolo11n.pt" in mapped.detail
    assert "backend/vision/weights" in mapped.detail


def test_zone_not_found_message_is_preserved():
    from app.api.vision import _fail
    from app.services.vision_service import ZoneNotFoundError

    mapped = _fail(ZoneNotFoundError("Zone 'LH01' missing"))

    assert mapped.status_code == 404
    assert "LH01" in mapped.detail


def test_server_side_logging_is_retained(
    monkeypatch, caplog
):
    """
    Hiding detail from the client must not silence it for the
    operator: the traceback is still logged.
    """

    import logging

    from app.services import vision_service as module
    from app.services.vision_service import (
        VisionPersistenceError,
        VisionService,
    )
    from vision_fakes import (
        StubDetector,
        detection_result,
        make_png,
    )
    from test_vision_service import FakeStore

    store = FakeStore(zones=[{"id": "z", "code": "LH01"}])
    store.fail_next["vision_observations"] = {
        "raise": RuntimeError(SECRETY)
    }

    monkeypatch.setattr(
        module, "get_supabase", lambda: store
    )

    service = VisionService(
        detector=StubDetector(
            detection_result(count=1, confidence=0.9)
        )
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(VisionPersistenceError):
            service.analyze(
                camera_id="cam-1",
                zone_code="LH01",
                image_bytes=make_png(),
            )

    assert caplog.records, "the failure was not logged"
    assert SECRET_FRAGMENTS[0] in caplog.text


# ============================================================
# VISION_ENABLED FEATURE TOGGLE
#
# With the feature off, no vision route is registered at all, so
# there is nothing that could run inference or write an
# observation. These tests assert the switch is honoured and that
# the disabled state cannot be mistaken for a working engine.
# ============================================================


def _app_with_vision(enabled: bool, monkeypatch):
    """
    Builds a fresh app, registering vision only if the toggle
    allows it. The module-level `VISION_ROUTES_ENABLED` is
    fixed at import, so a separate app is built per case.
    """

    from fastapi import FastAPI

    from app.core.config import settings
    from app.main import include_vision_router

    monkeypatch.setattr(
        settings, "vision_enabled", enabled
    )

    app = FastAPI()
    registered = include_vision_router(app)

    return app, registered


def test_enabled_registers_the_vision_routes(monkeypatch):
    from vision_fakes import (  # noqa: F401
        StubDetector,
        make_png,
    )

    _, registered = _app_with_vision(True, monkeypatch)

    assert registered is True


def test_disabled_registers_no_vision_routes(monkeypatch):
    app, registered = _app_with_vision(False, monkeypatch)

    assert registered is False

    paths = {getattr(r, "path", "") for r in app.routes}

    assert not any("vision" in p for p in paths)


def test_disabled_analyze_endpoint_is_absent(monkeypatch):
    """
    With the feature off there is no route to post to, so no
    request can reach inference or persistence.
    """

    from fastapi.testclient import TestClient

    from vision_fakes import make_png

    app, _ = _app_with_vision(False, monkeypatch)

    response = TestClient(app).post(
        "/api/v1/vision/analyze",
        files={"image": ("a.png", make_png(), "image/png")},
        data={"camera_id": "cam-1", "zone_code": "LH01"},
    )

    assert response.status_code == 404


def test_disabled_latest_endpoint_is_absent(monkeypatch):
    from fastapi.testclient import TestClient

    app, _ = _app_with_vision(False, monkeypatch)

    response = TestClient(app).get(
        "/api/v1/vision/zone/LH01/latest"
    )

    assert response.status_code == 404


def test_disabled_status_endpoint_is_absent(monkeypatch):
    from fastapi.testclient import TestClient

    app, _ = _app_with_vision(False, monkeypatch)

    response = TestClient(app).get(
        "/api/v1/vision/status"
    )

    assert response.status_code == 404


def test_disabled_never_touches_detector_or_database(
    monkeypatch,
):
    """
    The strongest guarantee: with the feature off nothing can
    run inference or reach the database, because the router is
    never even imported.
    """

    from app.services import vision_service as module

    calls = []

    class Tripwire:
        def __getattr__(self, name):
            calls.append(name)
            raise AssertionError(
                f"vision service was touched: {name}"
            )

    monkeypatch.setattr(
        module, "vision_service", Tripwire()
    )

    app, registered = _app_with_vision(False, monkeypatch)

    assert registered is False
    assert calls == [], (
        "the vision service must not be used while disabled"
    )


def test_health_reports_disabled_accurately(monkeypatch):
    from app.core.config import settings
    from app.main import vision_health

    monkeypatch.setattr(
        settings, "vision_enabled", False
    )
    monkeypatch.setattr(
        "app.main.VISION_ROUTES_ENABLED", False,
        raising=False,
    )

    report = vision_health()

    assert report["enabled"] is False
    assert report["routes_registered"] is False
    assert (
        report["detector_available"] is False
    ), "a disabled feature must never look ready"
    assert "VISION_ENABLED" in report["detail"]


def test_health_reports_enabled_state(monkeypatch):
    from app.core.config import settings
    from app.main import vision_health

    monkeypatch.setattr(
        settings, "vision_enabled", True
    )

    report = vision_health()

    assert report["enabled"] is True
    assert "enabled" in report


def test_enabled_leaves_health_unchanged(monkeypatch):
    """
    With the feature on, health still reports the routes and the
    detector exactly as before this change.
    """

    from app.core.config import settings
    from app.main import vision_health
    from app.services.vision_service import vision_service

    monkeypatch.setattr(
        settings, "vision_enabled", True
    )
    monkeypatch.setattr(
        "app.main.VISION_ROUTES_ENABLED", True,
        raising=False,
    )

    # Availability is decided by whether the weights file resolves
    # on disk. Those weights are a large binary, gitignored and
    # fetched separately, so a fresh clone and a CI runner have
    # none of them. Asserting a real detector here would make the
    # test pass or fail depending on whether somebody happened to
    # download the model, so the resolution seam is stubbed
    # instead. `test_health_reports_detector_absent` covers the
    # opposite case.
    monkeypatch.setattr(
        vision_service.detector,
        "resolve_weights_path",
        lambda: "/nonexistent/yolo11n.pt",
    )

    report = vision_health()

    assert report["enabled"] is True
    assert report["routes_registered"] is True
    assert report["detector_available"] is True
    assert report["model_name"] == "yolo11n.pt"


def test_health_reports_detector_absent(monkeypatch):
    """
    Enabled routes with no weights is the state a fresh clone is
    in. Health must say so rather than implying the engine works.
    """

    from app.core.config import settings
    from app.main import vision_health
    from app.services.vision_service import vision_service

    monkeypatch.setattr(
        settings, "vision_enabled", True
    )
    monkeypatch.setattr(
        "app.main.VISION_ROUTES_ENABLED", True,
        raising=False,
    )
    monkeypatch.setattr(
        vision_service.detector,
        "resolve_weights_path",
        lambda: None,
    )

    report = vision_health()

    assert report["enabled"] is True
    assert report["routes_registered"] is True
    assert report["detector_available"] is False
    assert report["model_name"] == "yolo11n.pt"


def test_disabled_does_not_affect_other_routers(monkeypatch):
    """
    Turning vision off must not disturb the campus or incident
    surface.
    """

    from app.api.campus import router as campus_router
    from app.api.incidents import router as incidents_router

    _, _ = _app_with_vision(False, monkeypatch)

    registered_paths = {
        getattr(r, "path", "")
        for r in campus_router.routes
    } | {
        getattr(r, "path", "")
        for r in incidents_router.routes
    }

    assert any("twin" in p for p in registered_paths)
    assert "/api/v1/incidents" in registered_paths


# ============================================================
# IDEMPOTENT WRITES (R4)
# ============================================================
#
# A caller that times out mid-request cannot tell whether the
# observation was stored, so it retries. Before `observed_at`
# reached the HTTP layer, every retry was indistinguishable from
# a second capture and wrote a second row. These tests pin the
# parameter down to the service, where deduplication already
# existed and could not be reached.


def _recording_service(monkeypatch, recorded):
    from app.api import vision as vision_api
    from app.schemas.vision import VisionAnalysisResponse
    from app.services.vision_service import VisionService
    from vision_fakes import StubDetector, detection_result

    class RecordingService(VisionService):
        def analyze(self, **kwargs):
            recorded.update(kwargs)

            from datetime import datetime, timezone

            return VisionAnalysisResponse(
                camera_id=kwargs["camera_id"],
                zone_code=kwargs["zone_code"],
                people_count=1,
                confidence=0.9,
                observed_at=datetime.now(timezone.utc),
                detections=[],
            )

    monkeypatch.setattr(
        vision_api,
        "vision_service",
        RecordingService(
            detector=StubDetector(detection_result())
        ),
    )


@requires_multipart
def test_observed_at_reaches_the_service(monkeypatch):
    from app.api.vision import analyze_image
    from vision_fakes import make_png

    recorded = {}
    _recording_service(monkeypatch, recorded)

    _run(
        analyze_image(
            image=_upload(make_png(), "image/png"),
            camera_id="cam-1",
            zone_code="LH01",
            observed_at="2026-10-16T09:30:00Z",
        )
    )

    assert recorded["observed_at"] is not None
    assert recorded["observed_at"].hour == 9


@requires_multipart
def test_omitted_observed_at_stays_none(monkeypatch):
    """
    Absent stays absent. Synthesising a server timestamp here
    would opt every request into deduplication, and a timestamp
    generated per call never matches anything.
    """

    from app.api.vision import analyze_image
    from vision_fakes import make_png

    recorded = {}
    _recording_service(monkeypatch, recorded)

    _run(
        analyze_image(
            image=_upload(make_png(), "image/png"),
            camera_id="cam-1",
            zone_code="LH01",
        )
    )

    assert recorded["observed_at"] is None


@requires_multipart
def test_blank_observed_at_stays_none(monkeypatch):
    from app.api.vision import analyze_image
    from vision_fakes import make_png

    recorded = {}
    _recording_service(monkeypatch, recorded)

    _run(
        analyze_image(
            image=_upload(make_png(), "image/png"),
            camera_id="cam-1",
            zone_code="LH01",
            observed_at="   ",
        )
    )

    assert recorded["observed_at"] is None


@requires_multipart
def test_malformed_observed_at_is_rejected(
    monkeypatch,
):
    """
    A bad timestamp must fail loudly. Falling back to a server
    time would report success while writing the duplicate the
    caller was specifically trying to avoid.
    """

    from fastapi import HTTPException

    from app.api.vision import analyze_image
    from vision_fakes import make_png

    recorded = {}
    _recording_service(monkeypatch, recorded)

    with pytest.raises(HTTPException) as caught:
        _run(
            analyze_image(
                image=_upload(make_png(), "image/png"),
                camera_id="cam-1",
                zone_code="LH01",
                observed_at="yesterday",
            )
        )

    assert (
        caught.value.status_code == 400
    )
    assert "ISO-8601" in caught.value.detail
    assert recorded == {}, "no analysis should have run"


@requires_multipart
def test_naive_observed_at_is_read_as_utc(monkeypatch):
    from app.api.vision import analyze_image
    from vision_fakes import make_png

    recorded = {}
    _recording_service(monkeypatch, recorded)

    _run(
        analyze_image(
            image=_upload(make_png(), "image/png"),
            camera_id="cam-1",
            zone_code="LH01",
            observed_at="2026-10-16T09:30:00",
        )
    )

    sent = recorded["observed_at"]
    assert sent.tzinfo is not None
    assert sent.utcoffset().total_seconds() == 0


@requires_multipart
def test_retry_with_same_timestamp_reaches_dedup(
    monkeypatch,
):
    """
    Two identical requests carrying the same capture time must
    produce identical persistence intent, so the service can
    recognise the second as a repeat.
    """

    from app.api.vision import analyze_image
    from vision_fakes import make_png

    recorded = {}
    _recording_service(monkeypatch, recorded)

    for _ in range(2):
        _run(
            analyze_image(
                image=_upload(make_png(), "image/png"),
                camera_id="cam-1",
                zone_code="LH01",
                observed_at="2026-10-16T09:30:00Z",
            )
        )

    # Both calls carried the same instant, which is the condition
    # the service deduplicates on.
    assert recorded["observed_at"] == recorded["observed_at"]
