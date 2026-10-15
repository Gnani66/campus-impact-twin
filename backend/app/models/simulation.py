"""
Domain models for Phase 10 simulation runs and options.

A simulation is a recorded what-if. Storing it is what makes a
recommendation reviewable: without the run, an assertion that
"the system chose the cheaper option" cannot be checked against
the evidence that was available at the time.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SimulationOption:
    """
    One candidate intervention within a run, scored.

    Infeasible options are represented rather than dropped. A
    shortlist that hides what it rejected is not decision
    support, it is a sales pitch.
    """

    intervention_code: str

    intervention_name: str

    feasible: bool

    feasibility_reasons: List[str] = field(default_factory=list)

    estimated_cost: float = 0.0

    projected_energy_reduction: Optional[float] = None

    projected_water_reduction: Optional[float] = None

    projected_waste_reduction: Optional[float] = None

    projected_co2_reduction: Optional[float] = None

    # Provenance for every projected figure. Without this the UI
    # cannot avoid presenting a simulation as a measurement.
    value_type: str = "simulated"

    disruption_level: str = "low"

    disruption_score: float = 0.0

    impact_score: float = 0.0

    confidence_score: float = 0.0

    cost_efficiency_score: float = 0.0

    feasibility_score: float = 0.0

    overall_score: float = 0.0

    worst_case_energy_kw: Optional[float] = None

    expected_case_energy_kw: Optional[float] = None

    best_case_energy_kw: Optional[float] = None

    band_available: bool = True

    assumptions: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """The shape the ranking rules consume."""

        return {
            "code": self.intervention_code,
            "name": self.intervention_name,
            "feasible": self.feasible,
            "feasibility_reasons": list(
                self.feasibility_reasons
            ),
            "estimated_cost": self.estimated_cost,
            "projected_energy_reduction": (
                self.projected_energy_reduction
            ),
            "disruption_level": self.disruption_level,
            "disruption_score": self.disruption_score,
            "impact_score": self.impact_score,
            "confidence_score": self.confidence_score,
            "cost_efficiency_score": (
                self.cost_efficiency_score
            ),
            "feasibility_score": self.feasibility_score,
            "overall_score": self.overall_score,
        }


@dataclass
class SimulationRun:
    """
    One what-if comparison for a zone.
    """

    id: Optional[str]

    zone_code: str

    scenario_name: str

    # The correlation run this reasoned from. Recorded so the
    # decision stays attached to the evidence that produced it
    # rather than to a fresh judgement that might differ.
    correlation_run_id: Optional[str] = None

    status: str = "completed"

    baseline: Dict[str, Any] = field(default_factory=dict)

    constraints: Dict[str, Any] = field(default_factory=dict)

    options: List[SimulationOption] = field(
        default_factory=list
    )

    recommendation: Optional[Dict[str, Any]] = None

    created_at: Optional[str] = None