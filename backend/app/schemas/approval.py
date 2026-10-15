"""
Schemas for Phase 11 approvals.

Two details are load-bearing rather than stylistic.

`extra="forbid"` on every request: an approval is a control
boundary, and a payload carrying fields the server does not
understand is exactly the shape of a confused-deputy request. A
review cannot smuggle in `reviewed_by` directly; it must name a
`reviewer`, which the service then records against a real
transition.

`status` on a review is restricted to approved or rejected, so a
client cannot walk the state machine by asking for `executed`.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.core.approval_rules import (
    REVIEWABLE_STATUSES,
)


class ApprovalCreate(BaseModel):
    """
    A recommendation being put to a human.
    """

    model_config = ConfigDict(extra="forbid")

    simulation_id: str = Field(min_length=1)

    simulation_option_id: str = Field(min_length=1)

    title: str = Field(min_length=1, max_length=255)

    description: Optional[str] = Field(
        default=None, max_length=2000
    )

    requested_by: str = Field(
        default="system", min_length=1, max_length=100
    )

    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApprovalReview(BaseModel):
    """
    A human decision.

    `status` may only be approved or rejected. Preparation and
    execution have their own endpoints so that each boundary
    produces its own audit event with its own actor.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1)

    reviewer: str = Field(min_length=1, max_length=100)

    # Required in practice for anything that closes the request.
    # The service enforces that, because whether a reason is
    # needed depends on the transition being attempted.
    reason: Optional[str] = Field(
        default=None, max_length=2000
    )

    @field_validator("status")
    @classmethod
    def _reviewable_only(cls, value: str) -> str:
        normalised = value.strip().lower()

        if normalised not in REVIEWABLE_STATUSES:
            raise ValueError(
                "A review may only set status to "
                f"{sorted(REVIEWABLE_STATUSES)}"
            )

        return normalised


class ApprovalEventResponse(BaseModel):
    """One entry in an approval's history."""

    id: Optional[str] = None

    previous_status: Optional[str] = None

    new_status: str

    actor: str

    reason: Optional[str] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)

    created_at: Optional[str] = None


class ApprovalResponse(BaseModel):
    """
    An approval request in full.
    """

    id: Optional[str] = None

    request_code: str

    simulation_id: str

    simulation_option_id: str

    title: str

    status: str

    description: Optional[str] = None

    requested_by: str = "system"

    requested_at: Optional[str] = None

    reviewed_at: Optional[str] = None

    reviewed_by: Optional[str] = None

    review_reason: Optional[str] = None

    execution_started_at: Optional[str] = None

    execution_completed_at: Optional[str] = None

    execution_result: Dict[str, Any] = Field(
        default_factory=dict
    )

    metadata: Dict[str, Any] = Field(default_factory=dict)

    created_at: Optional[str] = None

    updated_at: Optional[str] = None

    events: List[ApprovalEventResponse] = Field(
        default_factory=list
    )


class ApprovalReviewResponse(BaseModel):
    """
    The outcome of a review.

    Wraps the approval and the event that recorded it, because
    both halves matter: the new state, and the evidence that it
    was reached deliberately.
    """

    approval: ApprovalResponse

    event: ApprovalEventResponse


class ApprovalExecutionResponse(BaseModel):
    """
    The outcome of a simulated execution.

    `mode` is always `simulation`. The PRD requires execution to
    be simulated and approved before anything real happens, and
    this system never reaches campus infrastructure, so the field
    is not configurable.
    """

    approval: ApprovalResponse

    event: Optional[ApprovalEventResponse] = None

    execution_result: Dict[str, Any] = Field(
        default_factory=dict
    )