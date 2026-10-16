"""
Schemas for the AI campus copilot (Phase 13).

The shape of this contract is the whole point of the phase.

`answer` is prose and may come from the local model. `evidence`
and `recommendations` are computed in Python and never do. A
judge can read those two arrays and ignore the prose entirely,
and everything in them is traceable to a stored reading.

That separation is what makes the no-hallucination rule
enforceable rather than aspirational. Asking a model in a prompt
not to invent a sensor value is a request. Returning a
deterministically computed array beside its answer is a
guarantee, and the schema keeps them apart so neither can quietly
absorb the other.
"""

from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class CopilotRequest(BaseModel):
    """
    A question, optionally scoped to an entity.

    `extra="forbid"` because the copilot reads stored facts. A
    payload carrying its own `occupancy` or `temperature` would be
    an attempt to feed the model numbers it should be reading from
    the database, and silently ignoring it would be worse than
    refusing it.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
    )

    # Scopes the answer to one zone. Resolved against the twin's
    # own identifiers, so the caller cannot reference anything
    # that is not a real entity.
    entity_id: Optional[str] = Field(
        default=None, max_length=100
    )


class Evidence(BaseModel):
    """
    One verified fact.

    `value` is always a string rendered from a stored reading, and
    `source` names where it came from, so any statement in the
    prose can be traced to a row.
    """

    source: str

    value: str

    explanation: str


class CopilotRecommendation(BaseModel):
    """
    A suggested course of action.

    `requires_approval` defaults True and is never set False
    anywhere in this codebase. A recommendation is advice; the
    Phase 11 approval service is the only thing that can turn
    advice into an authorised action, and it is reached by a
    person clicking a button, not by this endpoint returning
    prose.
    """

    action: str

    rationale: str

    expected_effect: str

    requires_approval: bool = True

    # The entity this concerns, so a multi-zone overview can be
    # followed through to a specific room.
    entity_id: Optional[str] = None

    entity_name: Optional[str] = None


class CopilotResponse(BaseModel):
    """
    The copilot's answer.
    """

    # Prose. May be model-generated or deterministic; see
    # `source` below for which.
    answer: str

    intent: str

    evidence: List[Evidence] = Field(
        default_factory=list
    )

    recommendations: List[CopilotRecommendation] = Field(
        default_factory=list
    )

    # Where the prose came from: "llm" or "deterministic". Shown
    # in the UI so a reader knows whether a sentence was written
    # by a model or composed from the same numbers by code.
    source: str = "deterministic"

    # True when the local model could not be reached and the
    # deterministic path answered instead. Surfaced so a demo
    # does not quietly look like the model worked.
    llm_available: bool = True

    # Scoped entity, when the question named one.
    entity_id: Optional[str] = None

    entity_name: Optional[str] = None

    # Deterministic prioritisation, so a judge's question about
    # why one room outranks another can be answered from the
    # response itself.
    priority: Optional[float] = None

    # Anything the caller should know, such as a stale-data or
    # offline warning.
    caveats: List[str] = Field(default_factory=list)

    # Raw structured snapshot, included so a client can render
    # facts without re-querying.
    context: Dict[str, Any] = Field(
        default_factory=dict
    )