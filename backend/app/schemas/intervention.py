"""
Schemas for Phase 9 interventions.

Read-only surfaces. Nothing here creates or executes anything:
an intervention is a possibility, and this API exists so a
client can list the possibilities the evidence supports.
"""

from typing import List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class ImpactModelResponse(BaseModel):
    """
    One intervention's stated model for one metric.

    `evidence_source` is required rather than optional. An
    impact figure whose provenance cannot be stated is not a
    figure anyone should act on.
    """

    metric: str

    unit: str

    impact_type: str

    expected_value: Optional[float] = None

    minimum_value: Optional[float] = None

    maximum_value: Optional[float] = None

    confidence: Optional[float] = None

    evidence_source: str


class InterventionResponse(BaseModel):
    """One intervention from the library."""

    id: Optional[str] = None

    code: str

    name: str

    domain: str

    target_metric: str

    description: Optional[str] = None

    estimated_cost: float = 0.0

    estimated_duration_minutes: Optional[int] = None

    disruption_level: str = "low"

    # Both are returned so a client can render the level and
    # explain how it maps to a score rather than showing a bare
    # number.
    disruption_score: float = 0.0

    # The stored schema expresses evidence as weak / moderate /
    # strong rather than as a score, so that is what is exposed.
    minimum_evidence_quality: str = "moderate"

    enabled: bool = True

    assumptions: dict = Field(default_factory=dict)

    constraints: List[str] = Field(default_factory=list)

    impacts: List[ImpactModelResponse] = Field(
        default_factory=list
    )


class InterventionListResponse(BaseModel):
    """The library, with what the current evidence supports."""

    total: int

    enabled: int

    permitted: List[str] = Field(default_factory=list)

    # Refused interventions are listed with their reason. A
    # shortlist that hides what it rejected cannot be
    # distinguished from an oversight.
    refused: dict = Field(default_factory=dict)