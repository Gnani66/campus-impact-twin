"""
Simulation service (Phase 10).

The what-if engine, and the trust boundary of the whole
project.

It produces SIMULATED figures. It does not call anything that
actuates equipment, there is no code path here that reaches a
building system, and nothing it returns may be described as a
measured saving. A recommendation to apply an intervention is
advice; a separate, later, human-approved phase would be the
thing that does it.

The flow is fixed: load a stored correlation run, load the zone
and its evidence, load the intervention library, check
eligibility, check constraints, project impact, score cost,
disruption, confidence and feasibility, rank, archive, return.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.impact_rules import (
    DEFAULT_IMPACT_REFERENCES,
    VALUE_SIMULATED,
    calculate_cost_efficiency,
    calculate_overall_score,
    disruption_score,
)
from app.core.intervention_rules import (
    DEFAULT_INTERVENTION_CONFIG,
    ScenarioConstraints,
    check_feasibility,
    evidence_quality_for,
    quality_meets,
)
from app.core.simulation_rules import (
    STATUS_BLOCKED,
    STATUS_NO_SAFE_RECOMMENDATION,
    build_recommendation,
    comparison_summary,
    rank_options,
    validate_request,
)
from app.repositories.impact_repository import (
    correlation_context,
    latest_correlation_run,
)
from app.repositories.intervention_repository import (
    list_interventions,
)
from app.repositories.simulation_repository import (
    get_options,
    get_run,
    insert_options,
    insert_run,
)
from app.services.impact_service import (
    ImpactService,
    baseline_excess,
)


logger = logging.getLogger(__name__)


def _num(value, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class SimulationService:
    """
    Compares candidate interventions for a zone.
    """

    def __init__(
        self,
        impact_service: Optional[ImpactService] = None,
        intervention_config=DEFAULT_INTERVENTION_CONFIG,
    ):
        self.impact = impact_service or ImpactService()
        self.intervention_config = intervention_config

    # ----------------------------------------------------------
    # The run
    # ----------------------------------------------------------

    def run(
        self,
        zone_code: str,
        scenario_name: str,
        intervention_codes: List[str],
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a what-if and returns the comparison.

        Never raises for a missing data source. Every gap
        produces a status and a reason instead: a simulation
        that cannot be completed is a finding about the
        evidence, not a server fault.
        """

        constraints = constraints or {}

        # The stored schema has no code column, so codes are
        # resolved here rather than in SQL: a caller may address
        # an intervention by its code or by its name, and
        # filtering on the name column alone would reject every
        # code.
        library = [
            item
            for item in list_interventions()
            if not intervention_codes
            or item.code in intervention_codes
            or item.name in intervention_codes
        ]

        unknown = validate_request(
            intervention_codes,
            [item.code for item in library]
            + [item.name for item in library],
        )

        if unknown:
            return self._blocked(
                zone_code,
                scenario_name,
                constraints,
                (
                    "No intervention library entry exists for: "
                    + ", ".join(sorted(unknown))
                ),
            )

        run = latest_correlation_run(zone_code)

        if run is None:
            return self._blocked(
                zone_code,
                scenario_name,
                constraints,
                (
                    "No correlation run exists for this zone, so "
                    "there is no evidenced condition to plan "
                    "against."
                ),
            )

        if run.get("result_status") != "confirmed_candidate":
            return self._blocked(
                zone_code,
                scenario_name,
                constraints,
                (
                    "The latest correlation run concluded "
                    f"'{run.get('result_status')}', so there is "
                    "no evidence-supported condition to plan "
                    "against."
                ),
                correlation_run_id=run.get("id"),
                run=run,
            )

        context = correlation_context(zone_code)
        evidence_score = _num(run.get("evidence_score"))

        baseline = self._baseline(context, run)

        scenario = ScenarioConstraints(
            budget=_opt_float(constraints.get("budget")),
            max_disruption=constraints.get("max_disruption"),
            min_evidence_score=_opt_float(
                constraints.get("min_evidence_score")
            ),
            max_duration_minutes=_opt_int(
                constraints.get("max_duration_minutes")
            ),
            operating_window_only=bool(
                constraints.get("operating_window_only", False)
            ),
            requires_human_approval=bool(
                constraints.get(
                    "requires_human_approval", True
                )
            ),
        )

        excess = baseline_excess(
            baseline.get("energy_kw"),
            baseline.get("expected_energy_kw"),
        )

        options: List[Dict[str, Any]] = []
        intervention_ids: Dict[str, Optional[str]] = {}

        for intervention in library:
            option = self._evaluate(
                intervention,
                context,
                baseline,
                excess,
                evidence_score,
                scenario,
            )

            options.append(option)
            intervention_ids[option["code"]] = (
                intervention.id
            )

        ranked = rank_options(options)

        recommendation = build_recommendation(ranked)

        status = recommendation.status

        run_id = insert_run(
            zone_code=zone_code,
            scenario_name=scenario_name,
            correlation_run_id=run.get("id"),
            baseline=baseline,
            constraints=constraints,
            status=status,
        )

        if run_id:
            insert_options(run_id, ranked, intervention_ids)

        return {
            "simulation_id": run_id,
            "zone_code": zone_code,
            "scenario_name": scenario_name,
            "correlation_run_id": run.get("id"),
            "status": status,
            "baseline": baseline,
            "value_type": VALUE_SIMULATED,
            "recommendation": {
                "intervention_code": (
                    recommendation.intervention_code
                ),
                "overall_score": recommendation.overall_score,
                "reason": recommendation.reason,
                "status": recommendation.status,
            },
            "options": ranked,
            "comparison": comparison_summary(ranked),
        }

    # ----------------------------------------------------------
    # Per-option evaluation
    # ----------------------------------------------------------

    def _evaluate(
        self,
        intervention,
        context: Dict[str, Any],
        baseline: Dict[str, Any],
        excess_kw: float,
        evidence_score: float,
        scenario: ScenarioConstraints,
    ) -> Dict[str, Any]:
        """
        Scores one candidate option.

        Evidence eligibility is checked first and, when it
        fails, the option is returned infeasible with the reason
        attached. It is still scored, because a reader comparing
        options needs to see what the evidence would have
        supported had it been sufficient.
        """

        # --- evidence eligibility ---------------------------------
        reasons: List[str] = []

        eligible = quality_meets(
            evidence_quality_for(evidence_score),
            intervention.minimum_evidence_quality,
        )

        if not eligible:
            reasons.append(
                f"Evidence scores {evidence_score:.0f}/100 "
                f"({evidence_quality_for(evidence_score)}), "
                "which does not meet the "
                f"{intervention.minimum_evidence_quality} "
                "evidence this intervention requires."
            )

        # --- impact ------------------------------------------------
        assessment = self.impact.assess(
            intervention,
            context,
            baseline.get("energy_kw"),
            baseline.get("expected_energy_kw"),
        )

        # --- constraints -------------------------------------------
        feasibility, feasible, constraint_reasons = (
            check_feasibility(
                cost=intervention.cost,
                disruption_level=intervention.disruption_level,
                duration_minutes=(
                    intervention.duration_minutes
                ),
                constraints=scenario,
                declared=list(intervention.prerequisites),
                config=self.intervention_config,
            )
        )

        feasible = feasible and eligible
        reasons.extend(constraint_reasons)

        disruption = disruption_score(
            intervention.disruption_level
        )

        efficiency = calculate_cost_efficiency(
            assessment.impact_score,
            intervention.cost,
            cost_reference=scenario.budget,
        )

        overall = calculate_overall_score(
            impact_score=assessment.impact_score,
            confidence_score=assessment.confidence_score,
            feasibility_score=feasibility,
            cost_efficiency_score=efficiency,
            disruption_value=disruption,
        )

        energy = self.impact.project_energy(
            intervention, excess_kw
        )

        return {
            "code": intervention.code,
            "name": intervention.name,
            "domain": intervention.domain,
            "feasible": feasible,
            "feasibility_reasons": reasons,
            "estimated_cost": _num(intervention.cost),
            "disruption_level": intervention.disruption_level,
            "disruption_score": disruption,
            "impact_score": assessment.impact_score,
            "confidence_score": assessment.confidence_score,
            "feasibility_score": feasibility,
            "cost_efficiency_score": efficiency,
            "overall_score": overall,
            "projected_energy_reduction": energy.value,
            "projected_water_reduction": (
                assessment.water_reduction_litres
            ),
            "projected_waste_reduction": (
                assessment.waste_reduction_kg
            ),
            "projected_co2_reduction": (
                assessment.co2_reduction_kg
            ),
            # Provenance travels with the numbers so no interface
            # can present a simulation as a measurement.
            "value_type": VALUE_SIMULATED,
            "worst_case_energy_kw": energy.worst_case,
            "expected_case_energy_kw": energy.expected_case,
            "best_case_energy_kw": energy.best_case,
            "band_available": energy.band_available,
            "assumptions": {
                **intervention.metadata,
                "evidence_source": (
                    _evidence_source(intervention)
                ),
            },
        }

    # ----------------------------------------------------------
    # Baseline
    # ----------------------------------------------------------

    @staticmethod
    def _baseline(
        context: Dict[str, Any],
        run: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        The measured condition a scenario is compared against.

        Carries `baseline_measured` so the confidence score can
        distinguish a history-derived baseline from the
        capacity-derived nominal, and give credit only to the
        one that was actually measured.

        The figures come from current telemetry while the
        justification comes from the stored run. That split is
        deliberate: the run says why a condition exists, and the
        telemetry supplies the numbers an intervention is
        modelled against. The observation timestamp travels with
        the baseline so a reader can see how current it was.
        """

        picture = context.get("energy") or {}

        observation = context.get("observation") or {}

        return {
            "occupancy": _num(observation.get("value")),
            "energy_kw": picture.get("energy_kw"),
            "expected_energy_kw": picture.get(
                "expected_energy_kw"
            ),
            "capacity": picture.get("capacity"),
            "energy_observed_at": picture.get(
                "energy_observed_at"
            ),
            "evidence_score": _num(run.get("evidence_score")),
            "correlation_confidence": _num(
                run.get("confidence_score")
            ),
            "baseline_measured": bool(
                picture.get("baseline_measured")
            ),
        }

    # ----------------------------------------------------------
    # Blocked runs
    # ----------------------------------------------------------

    def _blocked(
        self,
        zone_code: str,
        scenario_name: str,
        constraints: Dict[str, Any],
        reason: str,
        correlation_run_id: Optional[str] = None,
        run: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        A simulation that could not proceed.

        Recorded like any other run. A decision that was
        considered and declined is exactly what an auditor asks
        about later.
        """

        run_id = insert_run(
            zone_code=zone_code,
            scenario_name=scenario_name,
            correlation_run_id=correlation_run_id,
            baseline={},
            constraints=constraints,
            status=STATUS_BLOCKED,
        )

        logger.info(
            "Simulation for '%s' blocked: %s", zone_code, reason
        )

        return {
            "simulation_id": run_id,
            "zone_code": zone_code,
            "scenario_name": scenario_name,
            "correlation_run_id": correlation_run_id,
            "status": STATUS_BLOCKED,
            "baseline": {},
            "value_type": VALUE_SIMULATED,
            "recommendation": {
                "intervention_code": None,
                "overall_score": None,
                "reason": reason,
                "status": STATUS_BLOCKED,
            },
            "options": [],
            "comparison": comparison_summary([]),
        }

    # ----------------------------------------------------------
    # Retrieval
    # ----------------------------------------------------------

    def load(
        self, run_id: str
    ) -> Optional[Dict[str, Any]]:
        """A stored run with its archived options."""

        run = get_run(run_id)

        if run is None:
            return None

        return {
            "simulation_id": run.get("id"),
            "zone_code": run.get("zone_code"),
            "scenario_name": run.get("scenario_name"),
            "correlation_run_id": run.get("correlation_run_id"),
            "status": run.get("status"),
            "baseline": run.get("baseline") or {},
            "constraints": run.get("constraints") or {},
            "value_type": VALUE_SIMULATED,
            "created_at": run.get("created_at"),
            "options": get_options(run_id),
        }


def _evidence_source(intervention) -> Optional[str]:
    """
    Where this intervention's expected figure came from.

    Falls back to naming the stored row, because a projection
    with no stated provenance is a number nobody should act on.
    """

    model = intervention.impact_for(intervention.target_metric)

    if model and model.evidence_source:
        return model.evidence_source

    return (
        f"Stored expectation on the intervention row "
        f"('{intervention.name}'), confidence "
        f"{intervention.confidence}"
    )


def _opt_float(value) -> Optional[float]:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value) -> Optional[int]:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


simulation_service = SimulationService()