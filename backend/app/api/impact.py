"""
Impact API (Phase 9).

Reports what each intervention would achieve for a zone, given
what the evidence currently supports.

Read-only with respect to the building: nothing here changes an
intervention or an equipment setting.
"""

import logging

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from app.core.impact_rules import (
    VALUE_MODELED,
    disruption_score,
)
from app.repositories.impact_repository import (
    correlation_context,
    latest_correlation_run,
)
from app.schemas.impact import (
    ImpactAnalyzeRequest,
    ImpactAnalyzeResponse,
)
from app.services.impact_service import (
    baseline_excess,
    impact_service,
)
from app.services.intervention_service import (
    intervention_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/impact",
    tags=["Impact"],
)


FAULT_DETAIL = "Impact analysis failed."

STATUS_NO_CONDITION = "no_evidenced_condition"


@router.post(
    "/analyze",
    response_model=ImpactAnalyzeResponse,
    summary="Model the impact of each eligible intervention",
)
def analyze_impact(request: ImpactAnalyzeRequest):
    """
    Projects the impact of every intervention the zone's
    evidence permits.

    Returns an empty shortlist rather than an error when there
    is no evidenced condition. "Nothing to act on" is a valid
    answer, and reporting it as a fault would train callers to
    treat a healthy building as a broken system.
    """

    try:
        run = latest_correlation_run(request.zone_code)

        if run is None:
            return ImpactAnalyzeResponse(
                zone_code=request.zone_code,
                status="blocked",
                baseline={},
                interventions=[],
            )

        if run.get("result_status") != "confirmed_candidate":
            return ImpactAnalyzeResponse(
                zone_code=request.zone_code,
                status=STATUS_NO_CONDITION,
                baseline={
                    "evidence_score": run.get("evidence_score"),
                    "correlation_status": run.get(
                        "result_status"
                    ),
                },
                interventions=[],
            )

        context = correlation_context(request.zone_code)
        picture = context.get("energy") or {}

        energy_kw = (
            request.energy_kw
            if request.energy_kw is not None
            else picture.get("energy_kw")
        )

        expected_kw = (
            request.expected_energy_kw
            if request.expected_energy_kw is not None
            else picture.get("expected_energy_kw")
        )

        excess = baseline_excess(energy_kw, expected_kw)

        split = intervention_service.for_zone(
            request.zone_code,
            run.get("evidence_score"),
        )


        results = []

        for intervention in split["permitted"]:
            assessment = impact_service.assess(
                intervention,
                context,
                energy_kw,
                expected_kw,
                business_priority=request.business_priority,
            )

            energy = impact_service.project_energy(
                intervention, excess
            )

            water = impact_service.project_scalar(
                intervention, "water", "litres/day"
            )

            waste = impact_service.project_scalar(
                intervention, "waste", "kg/week"
            )

            results.append(
                {
                    "code": intervention.code,
                    "name": intervention.name,
                    "feasible": True,
                    "feasibility_reasons": [],
                    "estimated_cost": intervention.estimated_cost,
                    "disruption_level": (
                        intervention.disruption_level
                    ),
                    "disruption_score": disruption_score(
                        intervention.disruption_level
                    ),
                    "impact_score": assessment.impact_score,
                    "confidence_score": (
                        assessment.confidence_score
                    ),
                    "feasibility_score": 100.0,
                    "cost_efficiency_score": 0.0,
                    "projected": [
                        item.as_dict()
                        for item in (
                            energy, water, waste
                        )
                        if item.value
                    ],
                    "value_type": VALUE_MODELED,
                }
            )

        # Refused interventions appear with their reason, so the
        # response explains the whole library rather than
        # silently trimming it.
        for code, reasons in split["refused"].items():
            results.append(
                {
                    "code": code,
                    "name": code,
                    "feasible": False,
                    "feasibility_reasons": reasons,
                    "estimated_cost": 0.0,
                    "disruption_level": "low",
                    "disruption_score": 0.0,
                    "impact_score": 0.0,
                    "confidence_score": 0.0,
                    "feasibility_score": 0.0,
                    "cost_efficiency_score": 0.0,
                    "projected": [],
                    "value_type": VALUE_MODELED,
                }
            )

        return ImpactAnalyzeResponse(
            zone_code=request.zone_code,
            status="completed",
            baseline={
                "occupancy": (
                    context.get("observation") or {}
                ).get("value"),
                "energy_kw": energy_kw,
                "expected_energy_kw": expected_kw,
                "avoidable_kw": excess,
                "capacity": picture.get("capacity"),
                "baseline_measured": picture.get(
                    "baseline_measured"
                ),
                "evidence_score": run.get("evidence_score"),
            },
            interventions=results,
        )

    except Exception as exc:
        logger.exception(
            "Impact analysis failed for '%s'",
            request.zone_code,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        ) from exc