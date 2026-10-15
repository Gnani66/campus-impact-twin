"""
Vision API (Phase 7).

`POST /api/v1/vision/analyze` accepts one uploaded still image
and returns the person count found in it. This is image
analysis, not a live camera feed: nothing here opens a stream,
polls a camera or runs on a timer.

`GET /api/v1/vision/zone/{zone_code}/latest` returns the newest
stored observation for a zone. It never reruns inference.

Note: importing this module requires `python-multipart`, which
FastAPI needs before it will define a route taking a file
upload. See the router registration in `app.main`.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Path,
    UploadFile,
    status,
)

from app.schemas.vision import (
    VisionAnalysisResponse,
    VisionObservationResponse,
)
from app.services.vision_service import (
    VisionPersistenceError,
    VisionService,
    ZoneNotFoundError,
    vision_service,
)
from vision.detector import (
    ImageValidationError,
    InferenceError,
    ModelUnavailableError,
    UnsupportedFormatError,
    UploadTooLargeError,
    VisionError,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/vision",
    tags=["Vision"],
)

# Uploads are read in bounded chunks. The size itself is
# enforced by the detector, but refusing to buffer an
# unbounded body first is cheaper than rejecting it later.
MAX_READ_BYTES = 10 * 1024 * 1024

MAX_CAMERA_ID_LENGTH = 128


# Faults the caller cannot act on report this exact message.
# The underlying exception stays in the log and as the
# exception cause, so nothing is lost to the operator while
# the client learns only that the request failed.
SERVER_FAULT_DETAIL = (
    "Vision processing failed. Nothing was recorded."
)


def _parse_observed_at(
    raw: Optional[str],
) -> Optional[datetime]:
    """
    Parses the optional `observed_at` form field.

    An absent or blank value means "the server decides", which is
    the historical behaviour and is not idempotent.

    A malformed value is rejected rather than ignored. Silently
    falling back to a server timestamp would defeat the entire
    purpose of the field: the caller asked for a retry to reuse a
    row, would be told it succeeded, and would have written a
    duplicate without ever learning why.

    A naive timestamp is read as UTC, matching the service's own
    normalisation, so the value stored is the value sent.

    A non-string is treated as absent. Calling this handler
    directly, rather than through FastAPI, passes the unpopulated
    `Form` sentinel as the default, and that means the same thing
    as not supplying the field.
    """

    if not isinstance(raw, str):
        return None

    text = raw.strip()

    if not text:
        return None

    normalised = text[:-1] + "+00:00" if text.endswith(
        "Z"
    ) else text

    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "observed_at must be an ISO-8601 timestamp, "
                "for example 2026-10-16T09:30:00Z"
            ),
        ) from None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def _fail(exc: Exception) -> HTTPException:
    """
    Maps a vision failure onto the project's established error
    shape, so a caller can distinguish "your upload is wrong"
    from "this deployment cannot detect right now".

    Client-facing detail is passed through only for failures the
    caller can act on: a bad upload, an unknown zone, or a
    missing model. Server-side faults get a fixed message,
    because a driver error can quote the database host and
    other infrastructure detail.
    """

    if isinstance(exc, UploadTooLargeError):
        # The `..._CONTENT_TOO_LARGE` spelling is the current one;
        # `HTTP_413_REQUEST_ENTITY_TOO_LARGE` is deprecated and
        # emits a DeprecationWarning on access.
        code = status.HTTP_413_CONTENT_TOO_LARGE
    elif isinstance(exc, UnsupportedFormatError):
        code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    elif isinstance(exc, ZoneNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, ModelUnavailableError):
        # The deployment is configured but the model is not
        # installed. Distinct from a server fault: retrying the
        # same upload will not help until it is fixed. The
        # message is written by this project and names no
        # infrastructure, so it stays actionable.
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(exc, VisionPersistenceError):
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    elif isinstance(exc, ImageValidationError):
        code = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, InferenceError):
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    elif isinstance(exc, VisionError):
        code = status.HTTP_400_BAD_REQUEST
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR

    if code == status.HTTP_503_SERVICE_UNAVAILABLE:
        detail = str(exc)
    elif code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        detail = SERVER_FAULT_DETAIL
    else:
        detail = str(exc)

    return HTTPException(
        status_code=code,
        detail=detail,
    )


@router.post(
    "/analyze",
    response_model=VisionAnalysisResponse,
    summary=(
        "Count people in an uploaded image and store the "
        "observation"
    ),
)
async def analyze_image(
    image: UploadFile = File(
        ...,
        description="A JPEG or PNG still image.",
    ),
    camera_id: str = Form(
        ...,
        description=(
            "Caller-supplied camera label. Free text; the "
            "schema has no camera table to validate against."
        ),
    ),
    zone_code: str = Form(
        ...,
        description="Zone the image was taken in.",
    ),
    observed_at: Optional[str] = Form(
        default=None,
        description=(
            "ISO-8601 capture time. Supplying it makes the "
            "write idempotent: retrying the same camera, zone "
            "and timestamp reuses the stored row instead of "
            "creating a duplicate. Omit it and every request is "
            "a new observation. A client-supplied timestamp is "
            "recorded as sent, so it is only appropriate when "
            "replaying a known capture."
        ),
    ),
) -> VisionAnalysisResponse:
    """
    Analyses one uploaded image.

    The response is returned only after the observation has
    been written. If persistence fails the request fails, and
    no success is reported.

    `observed_at` is optional. It exists so a caller that times
    out mid-request can retry safely: without it a retry is
    indistinguishable from a second capture and writes a second
    row. It is deliberately not synthesised here, because a
    server-generated key would have to be either unique per call
    (which never matches) or a fixed bucket (which would
    silently discard genuinely distinct observations).
    """

    if not camera_id or not camera_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="camera_id must not be empty",
        )

    if len(camera_id) > MAX_CAMERA_ID_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "camera_id must be at most "
                f"{MAX_CAMERA_ID_LENGTH} characters"
            ),
        )

    if not zone_code or not zone_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="zone_code must not be empty",
        )

    payload = await image.read(MAX_READ_BYTES + 1)

    capture_time = _parse_observed_at(observed_at)

    try:
        return vision_service.analyze(
            camera_id=camera_id.strip(),
            zone_code=zone_code.strip(),
            image_bytes=payload,
            declared_content_type=image.content_type,
            observed_at=capture_time,
        )
    except VisionError as exc:
        logger.warning(
            "Vision analysis rejected: %s", exc
        )
        raise _fail(exc) from exc
    except Exception as exc:
        # The traceback is logged above; the client gets a
        # fixed message so internal detail is never returned.
        logger.exception(
            "Vision analysis failed unexpectedly"
        )
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=SERVER_FAULT_DETAIL,
        ) from exc


@router.get(
    "/zone/{zone_code}/latest",
    response_model=VisionObservationResponse,
    summary=(
        "Latest stored vision observation for one zone"
    ),
)
def get_latest_observation(
    zone_code: str = Path(
        ...,
        description="Zone code, for example LH01.",
    ),
) -> VisionObservationResponse:
    """
    Returns the newest stored observation for a zone.

    Inference is never rerun. An absent observation is a 404,
    not an empty result, so a caller cannot mistake "never
    analysed" for "no people".
    """

    try:
        observation = (
            vision_service.latest_for_zone(
                zone_code=zone_code
            )
        )
    except ZoneNotFoundError as exc:
        raise _fail(exc) from exc
    except VisionError as exc:
        logger.warning(
            "Latest vision lookup failed: %s", exc
        )
        raise _fail(exc) from exc
    except Exception as exc:
        logger.exception(
            "Latest vision lookup failed unexpectedly"
        )
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=SERVER_FAULT_DETAIL,
        ) from exc

    if observation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No vision observation stored for zone "
                f"'{zone_code}'"
            ),
        )

    return observation


@router.get(
    "/status",
    summary="Whether person detection can run",
)
def get_vision_status() -> dict:
    """
    Reports detector readiness.

    Useful because the model may legitimately be absent in a
    development checkout: the API then runs with the vision
    routes unavailable rather than failing to start.
    """

    return {
        "enabled": True,
        "detector_available": (
            vision_service.is_available()
        ),
        "confidence_threshold": (
            vision_service.detector.confidence_threshold
        ),
        "iou_threshold": (
            vision_service.detector.iou_threshold
        ),
        "model_name": vision_service.detector.model_name,
        "observation_type": "people_count",
    }