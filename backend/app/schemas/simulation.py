"""
Schemas for Phase 10 what-if simulation.

The response shape is deliberately rich. A decision support
system that returns only a winner is a dashboard; one that
returns the runner-up, the rejected options and the reason each
was refused is something a person can actually decide with.
"""

from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class SimulationConstraints(BaseModel):
    """
    The limits a caller places on a what-if.

    Absent does not mean unlimited. A missing budget falls back
    to a configured cost reference so cost still counts for
    something, rather than every option looking free.
    """

    model_config = ConfigDict(extra="forbid")

    budget: Optional[float] = Field(default=None, ge=0)

    max_disruption: Optional[str] = None

    min_evidence_score: Optional[float] = Field(
        default=None, ge=0, le=100
    )

    max_duration_minutes: Optional[int] = Field(
        default=None, ge=0
    )

    operating_window_only: bool = False

    requires_human_approval: bool = True

    @field_validator("max_disruption")
    @classmethod
    def _known_level(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        if value.lower() not in ("low", "medium", "high"):
            raise ValueError(
                "max_disruption must be low, medium or high"
            )

        return value.lower()


class SimulationRequest(BaseModel):
    """A what-if to run."""

    model_config = ConfigDict(extra="forbid")

    zone_code: str = Field(min_length=1, max_length=50)

    scenario_name: str = Field(
        min_length=1, max_length=200
    )

    intervention_codes: List[str] = Field(
        default_factory=list,
        max_length=25,
    )

    constraints: SimulationConstraints = Field(
        default_factory=SimulationConstraints
    )


class RecommendationResponse(BaseModel):
    """
    The engine's preferred option, or an explicit refusal.

    `reason` is always populated. An unexplained
    recommendation is an instruction, not decision support, and
    an unexplained refusal is worse than no answer.
    """

    intervention_code: Optional[str] = None

    overall_score: Optional[float] = None

    reason: str

    status: str


class SimulationOptionResponse(BaseModel):
    """
    One scored option, feasible or not.

    Infeasible options are returned with their reasons. What was
    rejected is part of the answer.
    """

    code: str

    name: str

    domain: Optional[str] = None

    feasible: bool

    feasibility_reasons: List[str] = Field(
        default_factory=list
    )

    estimated_cost: float = 0.0

    disruption_level: str

    disruption_score: float

    impact_score: float

    confidence_score: float

    feasibility_score: float

    cost_efficiency_score: float

    overall_score: float

    projected_energy_reduction: Optional[float] = None

    projected_water_reduction: Optional[float] = None

    projected_waste_reduction: Optional[float] = None

    projected_co2_reduction: Optional[float] = None

    # Every projected figure is a simulation. Carried
    # explicitly so no client can render it as a measurement.
    value_type: str = "simulated"

    worst_case_energy_kw: Optional[float] = None

    expected_case_energy_kw: Optional[float] = None

    best_case_energy_kw: Optional[float] = None

    band_available: bool = True

    assumptions: Dict[str, Any] = Field(default_factory=dict)


class SimulationResponse(BaseModel):
    """
    The full what-if result.
    """

    simulation_id: Optional[str] = None

    zone_code: str

    scenario_name: Optional[str] = None

    correlation_run_id: Optional[str] = None

    # completed | blocked | no_safe_recommendation
    status: str

    baseline: Dict[str, Any] = Field(default_factory=dict)

    constraints: Dict[str, Any] = Field(default_factory=dict)

    value_type: str = "simulated"

    recommendation: RecommendationResponse

    options: List[SimulationOptionResponse] = Field(
        default_factory=list
    )

    comparison: Dict[str, Any] = Field(default_factory=dict)

    created_at: Optional[str] = None