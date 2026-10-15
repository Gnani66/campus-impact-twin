"""
Simulation API (Phase 10).

The what-if endpoints, and the trust boundary of the project.

Nothing here actuates equipment. A simulation returns modelled
figures and a recommendation; applying it is a later, separate,
human-approved step. There is deliberately no write path from
this module to any building system.
"""

import logging

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from app.schemas.simulation import (
    SimulationRequest,
    SimulationResponse,
)
from app.services.simulation_service import simulation_service


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/simulation",
    tags=["Simulation"],
)


# Returned when a query fails for an unexpected reason. The
# underlying exception names tables and connection details, so
# it is logged and never sent to the caller.
FAULT_DETAIL = "Simulation failed."


@router.post(
    "/run",
    response_model=SimulationResponse,
    summary="Run a what-if and rank the options",
)
def run_simulation(request: SimulationRequest):
    """
    Compares candidate interventions for a zone.

    Three outcomes, all of them valid answers:

    * `completed` with a recommendation,
    * `no_safe_recommendation` when every option violated a
      constraint,
    * `blocked` when there was no evidenced condition to plan
      against.

    An endpoint that only ever returns success would be a
    dashboard. The ability to decline is what makes the
    recommendations it does make worth reading.
    """

    try:
        result = simulation_service.run(
            zone_code=request.zone_code,
            scenario_name=request.scenario_name,
            intervention_codes=request.intervention_codes,
            constraints=request.constraints.model_dump(),
        )

        return SimulationResponse(**result)

    except Exception as exc:
        logger.exception(
            "Simulation failed for '%s'", request.zone_code
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        ) from exc


@router.get(
    "/{run_id}",
    response_model=SimulationResponse,
    summary="A stored simulation run",
)
def get_simulation(run_id: str):
    """
    An archived run with its options.

    Re-reading a past decision is how the audit trail works, so
    this returns what was recorded rather than recomputing it.
    """

    try:
        result = simulation_service.load(run_id)

        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No simulation run with that id.",
            )

        return SimulationResponse(**result)

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Failed to read simulation run %s", run_id
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        ) from exc


@router.get(
    "/{run_id}/comparison",
    summary="Side-by-side comparison for a stored run",
)
def compare_simulation(run_id: str):
    """
    The trade-off view.

    Returns every option with its scores and its reasons, not
    just the winner. A comparison that hides the rejected
    options is not decision support.
    """

    try:
        result = simulation_service.load(run_id)

        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No simulation run with that id.",
            )

        options = result.get("options") or []

        feasible = [
            option
            for option in options
            if option.get("feasible")
        ]
        infeasible = [
            option
            for option in options
            if not option.get("feasible")
        ]

        best = (
            max(
                feasible,
                key=lambda option: _score(option),
            )
            if feasible
            else None
        )

        return {
            "simulation_id": run_id,
            "zone_code": result.get("zone_code"),
            "status": result.get("status"),
            "value_type": result.get("value_type", "simulated"),
            "baseline": result.get("baseline", {}),
            "recommended": (
                (best.get("intervention") or {}).get("code")
                if best
                else None
            ),
            "totals": {
                "options": len(options),
                "feasible": len(feasible),
                "infeasible": len(infeasible),
            },
            "options": options,
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Failed to compare simulation run %s", run_id
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        ) from exc


def _score(option) -> float:
    try:
        return float(option.get("overall_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0