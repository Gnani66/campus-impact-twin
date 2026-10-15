"""
Campus incident API.

Read-only. Incidents are produced by the intelligence engine as
telemetry is persisted, never written directly through this API.
"""

from typing import Optional

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
    RuleEvaluationResponse,
)
from app.services.intelligence_service import (
    intelligence_service,
)


router = APIRouter(
    prefix="/api/v1/incidents",
    tags=["Incidents"],
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
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Failed to load incident summary: "
                f"{exc}"
            ),
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
            limit=limit,
        )

        return [
            IncidentResponse(**row) for row in rows
        ]

    except Exception as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Failed to load incidents: "
                f"{exc}"
            ),
        ) from exc
