"""
Correlation API (Phase 8).

Two read-only endpoints. Neither accepts evidence: a caller
names a zone and says whether it is inside its operating
schedule, and the engine reads everything else from stored
observations and telemetry. A verdict cannot be manufactured by
posting invented numbers here.
"""

import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.schemas.correlation import (
    CorrelationRequest,
    CorrelationResponse,
)
from app.services.correlation_service import (
    correlation_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/correlation",
    tags=["Correlation"],
)


# Returned when an analysis fails for an unexpected reason. The
# underlying exception names the table and connection detail
# involved, so it is logged and never sent to the caller.
CORRELATION_FAULT_DETAIL = (
    "Correlation analysis failed."
)


@router.post(
    "/analyze",
    response_model=CorrelationResponse,
    summary=(
        "Judge a zone against vision, telemetry and schedule"
    ),
)
def analyze_zone(
    request: CorrelationRequest,
) -> CorrelationResponse:
    """
    Runs the evidence gate for one zone.

    Returns `confirmed_candidate` only when every requirement is
    met, `needs_review` when something looks wrong but the
    evidence is incomplete, and `normal` when nothing is
    supported by the evidence.
    """

    try:
        verdict = correlation_service.correlate(
            zone_code=request.zone_code,
            schedule_active=request.schedule_active,
        )

        return CorrelationResponse(**verdict)

    except Exception as exc:
        logger.exception(
            "Correlation analysis failed for '%s'",
            request.zone_code,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=CORRELATION_FAULT_DETAIL,
        ) from exc


@router.get(
    "/zone/{zone_code}",
    summary="Recorded correlation runs for a zone, newest first",
)
def zone_runs(
    zone_code: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """
    The audit trail for a zone.

    Every analysis is recorded, including the ones that concluded
    nothing. Those are the ones a reviewer asks about later.
    """

    try:
        runs = correlation_service.recent_runs(
            zone_code, limit=limit
        )

    except Exception as exc:
        logger.exception(
            "Failed to read correlation runs for '%s'",
            zone_code,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=CORRELATION_FAULT_DETAIL,
        ) from exc

    return {"zone_code": zone_code, "runs": runs}