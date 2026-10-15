"""
Intervention API (Phase 9).

Read-only. Nothing here creates, modifies or executes an
intervention: the endpoints exist so a client can see what the
library contains and what the current evidence permits.
"""

import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.core.impact_rules import disruption_score
from app.repositories.impact_repository import (
    latest_correlation_run,
)
from app.schemas.intervention import (
    InterventionListResponse,
    InterventionResponse,
    ImpactModelResponse,
)
from app.services.intervention_service import (
    intervention_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/interventions",
    tags=["Interventions"],
)


FAULT_DETAIL = "Failed to read the intervention library."


def _serialise(intervention) -> InterventionResponse:
    return InterventionResponse(
        id=intervention.id,
        code=intervention.code,
        name=intervention.name,
        domain=intervention.domain,
        target_metric=intervention.target_metric,
        description=intervention.description,
        estimated_cost=intervention.cost,
        estimated_duration_minutes=(
            intervention.duration_minutes
        ),
        disruption_level=intervention.disruption_level,
        disruption_score=disruption_score(
            intervention.disruption_level
        ),
        minimum_evidence_quality=(
            intervention.minimum_evidence_quality
        ),
        enabled=intervention.enabled,
        assumptions=intervention.metadata,
        constraints=list(intervention.prerequisites),
        impacts=[
            ImpactModelResponse(
                metric=model.metric,
                unit=model.unit,
                impact_type=model.impact_type,
                expected_value=model.expected_value,
                minimum_value=model.minimum_value,
                maximum_value=model.maximum_value,
                confidence=model.confidence,
                evidence_source=model.evidence_source,
            )
            for model in intervention.impacts
        ],
    )


@router.get(
    "",
    response_model=InterventionListResponse,
    summary="The intervention library and its eligibility",
)
def list_interventions(
    domain: str = Query(default=None),
    zone_code: str = Query(default=None),
):
    """
    Lists the library.

    Supplying `zone_code` adds the eligibility split for that
    zone's evidence: what may be offered, and what is refused
    and why. Refusals are returned rather than hidden, so an
    absent option can be told apart from an oversight.
    """

    try:
        library = intervention_service.available(
            domain=domain,
            eligible_only=False,
        )

        permitted_codes: list = []
        refused: dict = {}

        if zone_code:
            run = latest_correlation_run(zone_code)

            evidence = (
                run.get("evidence_score")
                if run is not None
                else None
            )

            split = intervention_service.eligible(
                library, evidence
            )

            permitted_codes = [
                item.code for item in split["permitted"]
            ]
            refused = split["refused"]

        return InterventionListResponse(
            total=len(library),
            enabled=sum(
                1 for item in library if item.enabled
            ),
            permitted=permitted_codes,
            refused=refused,
        )

    except Exception as exc:
        logger.exception(
            "Failed to list the intervention library"
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        ) from exc


@router.get(
    "/{code}",
    response_model=InterventionResponse,
    summary="One intervention by code",
)
def get_intervention(code: str):
    """
    A single intervention, including its impact models.

    Disabled interventions remain readable. An operator needs to
    see what exists in order to re-enable it.
    """

    try:
        library = intervention_service.available(
            eligible_only=False
        )

        matches = [
            item for item in library if item.code == code
        ]

        if not matches:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No intervention with code '{code}'."
                ),
            )

        return _serialise(matches[0])

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Failed to read intervention '%s'", code
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        ) from exc