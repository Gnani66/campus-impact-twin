"""
Simulation repository.

Phase 10 writes two tables: one run and its options. Runs and
options are persisted even when the outcome was a refusal,
because a decision that was considered and declined is exactly
the thing an auditor asks about later.
"""

import logging
from typing import Any, Dict, List, Optional

from app.db.supabase import get_supabase


logger = logging.getLogger(__name__)


RUNS_TABLE = "simulation_runs"
OPTIONS_TABLE = "simulation_options"


def insert_run(
    zone_code: str,
    scenario_name: str,
    correlation_run_id: Optional[str],
    baseline: Dict[str, Any],
    constraints: Dict[str, Any],
    status: str,
) -> Optional[str]:
    """
    Records a simulation run.

    Returns None on failure rather than raising. A simulation
    that could not be archived is still a valid answer to the
    question asked, and refusing to return it would turn a
    storage problem into a user-visible outage. The caller logs
    the loss and reports the result.
    """

    try:
        result = (
            get_supabase()
            .table(RUNS_TABLE)
            .insert(
                {
                    "zone_code": zone_code,
                    "scenario_name": scenario_name,
                    "correlation_run_id": correlation_run_id,
                    "baseline": baseline,
                    "constraints": constraints,
                    "status": status,
                }
            )
            .execute()
            .data
        )

        if result:
            return str(result[0].get("id"))

        return None

    except Exception:
        logger.exception(
            "Simulation run for '%s' could not be archived",
            zone_code,
        )

        return None


def insert_options(
    run_id: str,
    options: List[Dict[str, Any]],
    intervention_ids: Dict[str, Optional[str]],
) -> bool:
    """
    Records every option in a run, feasible or not.

    `intervention_ids` maps an intervention code to its row id.
    An option whose intervention could not be resolved is
    skipped rather than written with a null reference, since the
    column is not nullable and the row would be rejected.
    """

    rows: List[Dict[str, Any]] = []

    for option in options:
        code = option.get("code")
        intervention_id = intervention_ids.get(code)

        if not intervention_id:
            logger.warning(
                "Skipping archive of option '%s': no stored "
                "intervention row",
                code,
            )
            continue

        rows.append(
            {
                "simulation_run_id": run_id,
                "intervention_id": intervention_id,
                "feasible": bool(
                    option.get("feasible", False)
                ),
                "feasibility_reasons": option.get(
                    "feasibility_reasons", []
                ),
                "estimated_cost": option.get(
                    "estimated_cost", 0
                ),
                "projected_energy_reduction": option.get(
                    "projected_energy_reduction"
                ),
                "projected_water_reduction": option.get(
                    "projected_water_reduction"
                ),
                "projected_waste_reduction": option.get(
                    "projected_waste_reduction"
                ),
                "projected_co2_reduction": option.get(
                    "projected_co2_reduction"
                ),
                "disruption_score": option.get(
                    "disruption_score"
                ),
                "impact_score": option.get("impact_score"),
                "confidence_score": option.get(
                    "confidence_score"
                ),
                "overall_score": option.get("overall_score"),
                "assumptions": option.get("assumptions", {}),
            }
        )

    if not rows:
        return False

    try:
        (
            get_supabase()
            .table(OPTIONS_TABLE)
            .insert(rows)
            .execute()
        )

        return True

    except Exception:
        logger.exception(
            "Simulation options for run %s could not be "
            "archived",
            run_id,
        )

        return False


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    """One simulation run by id."""

    try:
        result = (
            get_supabase()
            .table(RUNS_TABLE)
            .select(
                "id,zone_code,correlation_run_id,scenario_name,"
                "baseline,constraints,status,created_at"
            )
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception(
            "Failed to read simulation run %s", run_id
        )

        return None

    rows = result.data or []

    return rows[0] if rows else None


def get_options(run_id: str) -> List[Dict[str, Any]]:
    """
    The archived options for a run, joined to their intervention.

    The join is done here rather than as an embedded PostgREST
    select. Embedding resolves the relationship through a
    generated alias that does not exist on this schema, and the
    failure is silent in the worst way: the options come back
    empty and a run appears to have no findings at all. Two
    explicit queries are slower and actually work.
    """

    try:
        result = (
            get_supabase()
            .table(OPTIONS_TABLE)
            .select(
                "id,feasible,feasibility_reasons,"
                "estimated_cost,projected_energy_reduction,"
                "projected_water_reduction,"
                "projected_waste_reduction,"
                "projected_co2_reduction,disruption_score,"
                "impact_score,confidence_score,overall_score,"
                "assumptions,created_at,intervention_id"
            )
            .eq("simulation_run_id", run_id)
            .order("overall_score", desc=True)
            .execute()
        )
    except Exception:
        logger.exception(
            "Failed to read options for run %s", run_id
        )

        return []

    rows = result.data or []

    if not rows:
        return []

    interventions = _interventions_by_id(
        [
            row.get("intervention_id")
            for row in rows
            if row.get("intervention_id")
        ]
    )

    for row in rows:
        row["intervention"] = interventions.get(
            str(row.get("intervention_id")), {}
        )

    return rows


def _interventions_by_id(
    intervention_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """
    Fetches the interventions referenced by a set of options.

    A missing intervention leaves its options present but
    unnamed rather than dropping them: a comparison that hides
    an option because its label is missing is worse than one
    that shows it as unidentified.
    """

    unique = list({str(i) for i in intervention_ids if i})

    if not unique:
        return {}

    try:
        result = (
            get_supabase()
            .table("interventions")
            .select("id,name,domain,cost,metadata")
            .in_("id", unique)
            .execute()
        )
    except Exception:
        logger.exception(
            "Failed to read interventions for options"
        )

        return {}

    resolved = {}

    for row in result.data or []:
        metadata = (
            row.get("metadata")
            if isinstance(row.get("metadata"), dict)
            else {}
        )

        resolved[str(row.get("id"))] = {
            "code": metadata.get("code") or row.get("name"),
            "name": row.get("name"),
            "domain": row.get("domain"),
            "cost": row.get("cost"),
            "disruption_level": metadata.get(
                "disruption_level"
            ),
        }

    return resolved