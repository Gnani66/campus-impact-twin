"""
Schemas for Phase 9 impact analysis.

`value_type` appears on every projected figure and is not
optional. The PRD requires modelled outcomes to be labelled as
modelled, and the only reliable place to enforce that is the
response contract itself: a required field cannot be forgotten
by a serialiser, whereas a convention can.
"""

from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class ImpactAnalyzeRequest(BaseModel):
    """
    What to analyse.

    Extra fields are forbidden so a caller cannot post an
    expected figure and have it silently dropped while
    believing it was used.
    """

    model_config = ConfigDict(extra="forbid")

    zone_code: str = Field(min_length=1, max_length=50)

    # Optional overrides for exploring a what-if. Absent means
    # "use the measured values", never "use zero".
    energy_kw: Optional[float] = None

    expected_energy_kw: Optional[float] = None

    business_priority: float = 1.0

    @field_validator("business_priority")
    @classmethod
    def _bounded(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError(
                "business_priority must be between 0 and 1"
            )

        return value


class ProjectedValue(BaseModel):
    """
    A projected figure with its provenance and its band.
    """

    metric: str

    value: float

    unit: str

    # measured | modeled | estimated | simulated
    value_type: str

    confidence: Optional[float] = None

    worst_case: Optional[float] = None

    expected_case: Optional[float] = None

    best_case: Optional[float] = None

    # False when the model gave no basis for a spread. A
    # zero-width band is an absence of information, not
    # certainty, and the client must be able to say so.
    band_available: bool = True


class InterventionImpactResponse(BaseModel):
    """Impact and confidence for one intervention."""

    code: str

    name: str

    feasible: bool

    feasibility_reasons: list = Field(default_factory=list)

    estimated_cost: float = 0.0

    disruption_level: str

    disruption_score: float

    impact_score: float

    confidence_score: float

    feasibility_score: float

    cost_efficiency_score: float

    projected: list = Field(default_factory=list)

    value_type: str = "simulated"


class ImpactAnalyzeResponse(BaseModel):
    """
    The impact picture for a zone.
    """

    zone_code: str

    status: str

    baseline: dict = Field(default_factory=dict)

    interventions: list = Field(default_factory=list)

    value_type: str = "simulated"