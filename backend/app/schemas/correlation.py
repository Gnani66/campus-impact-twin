"""
Schemas for the multi-source correlation engine (Phase 8).

A correlation response is a recorded judgement about a zone,
made from vision, telemetry and schedule together. It states
what was observed, which evidence requirements were met, and
what the engine concluded from that.

The wording is constrained deliberately. Nothing here reports a
confirmed leak or a measured saving: the engine produces
modelled candidates and the response says so. `root_cause` is
free text for that reason and is expected to read
"Potential ..." rather than "Confirmed ...".
"""

from typing import List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class CorrelationRequest(BaseModel):
    """
    What the caller wants judged.

    Only the zone and its operating state are supplied. The
    evidence itself is read from stored observations and
    telemetry rather than accepted from the caller, so a
    response cannot be manufactured by posting invented numbers
    to this endpoint.

    `extra="forbid"` is load-bearing rather than pedantic:
    Pydantic ignores unknown fields by default, so without it a
    caller could post `occupancy=0` and `energy_kw=8.5`, have
    them silently dropped, and believe the engine had used
    them. Rejecting makes the limit explicit.
    """

    model_config = ConfigDict(extra="forbid")

    zone_code: str = Field(
        min_length=1,
        max_length=50,
    )

    schedule_active: bool = True


class EvidenceFinding(BaseModel):
    """
    One gate condition and its outcome, as reported.
    """

    name: str

    passed: bool

    score: float

    reason: str


class CorrelationResponse(BaseModel):
    """
    The engine's conclusion for one zone.

    Every field is derived from stored evidence. The evidence
    list is included so the conclusion can be checked rather
    than taken on trust.
    """

    zone_code: str

    result_status: str = Field(
        description=(
            "normal, needs_review or confirmed_candidate."
        )
    )

    root_cause: Optional[str] = None

    evidence_score: float

    confidence_score: float

    # The measurements the judgement was made from. Kept so a
    # stored correlation run can be read without re-querying the
    # sources it used, which may since have changed.
    occupancy: Optional[float] = None

    energy_kw: Optional[float] = None

    expected_energy_kw: Optional[float] = None

    energy_ratio: Optional[float] = None

    occupancy_ratio: Optional[float] = None

    occupancy_state: Optional[str] = None

    schedule_active: bool = True

    evidence: List[EvidenceFinding] = Field(
        default_factory=list
    )

    # The id of the stored run, when persistence succeeded.
    correlation_run_id: Optional[str] = None