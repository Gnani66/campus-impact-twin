"""
Campus incident API.

Read-only. Incidents are produced by the intelligence engine as
telemetry is persisted, never written directly through this API.
"""

from typing import Optional

import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.core.config import settings
from app.schemas.intelligence import (
    IncidentResponse,
    IntelligenceSummary,
)
from app.services.intelligence_service import (
    intelligence_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/incidents",
    tags=["Incidents"],
)


# Returned to the client when a query fails for an unexpected
# reason. The underlying exception names the table, column or
# connection detail involved, so it is logged for the operator
# and never sent to the caller. Mirrors the rule already applied
# by the vision API.
INCIDENTS_FAULT_DETAIL = (
    "Failed to load incident data."
)


@router.get(
    "/summary",
    response_model=IntelligenceSummary,
    summary="Incident counts by severity for one campus",
)
def get_incident_summary(
    campus_code: str = Query(
        default=settings.default_campus_code
    ),
) -> IntelligenceSummary:
    try:
        return intelligence_service.summary(
            campus_code
        )
    except Exception as exc:
        # The traceback is logged here; the client receives a
        # fixed message so internal detail is never disclosed.
        logger.exception(
            "Failed to load incident summary for '%s'",
            campus_code,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=INCIDENTS_FAULT_DETAIL,
        ) from exc


@router.get(
    "",
    response_model=list[IncidentResponse],
    summary="List incidents, most severe first",
)
def get_incidents(
    campus_code: str = Query(
        default=settings.default_campus_code
    ),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description=(
            "open, acknowledged, investigating, resolved "
            "or dismissed"
        ),
    ),
    severity: Optional[str] = Query(
        default=None,
        description=(
            "low, medium, high or critical"
        ),
    ),
    category: Optional[str] = Query(
        default=None,
        description=(
            "energy, environment, occupancy, water, "
            "equipment, safety, maintenance or other"
        ),
    ),
    zone_code: Optional[str] = Query(
        default=None,
        alias="zone",
        description=(
            "Zone code, for example LH01. Narrows to incidents "
            "in that zone; an unknown code matches nothing."
        ),
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
) -> list:
    try:
        rows = intelligence_service.list_incidents(
            campus_code=campus_code,
            status=status_filter,
            severity=severity,
            category=category,
            zone_code=zone_code,
            limit=limit,
        )

        return [
            IncidentResponse(**row) for row in rows
        ]

    except Exception as exc:
        logger.exception(
            "Failed to load incidents for '%s'",
            campus_code,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=INCIDENTS_FAULT_DETAIL,
        ) from exc
