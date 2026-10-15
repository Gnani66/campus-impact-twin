"""
Domain models for Phase 11 approvals.

Plain dataclasses, matching the Phase 9 and 10 models. The
specification sketches SQLAlchemy ORM classes, but this project
talks to Supabase over PostgREST and has no declarative base, so
these are the same domain objects without an ORM. The domain
model is unchanged; only the persistence mechanism differs.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ApprovalEvent:
    """
    One immutable transition in an approval's history.

    Append-only by construction: nothing in the codebase updates
    or deletes an event. The current state lives on the request;
    this is how it got there.
    """

    id: Optional[str]

    approval_request_id: str

    new_status: str

    actor: str

    previous_status: Optional[str] = None

    reason: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    created_at: Optional[str] = None

    @classmethod
    def from_row(
        cls, row: Dict[str, Any]
    ) -> "ApprovalEvent":
        return cls(
            id=row.get("id"),
            approval_request_id=str(
                row.get("approval_request_id")
            ),
            new_status=row.get("new_status") or "",
            actor=row.get("actor") or "",
            previous_status=row.get("previous_status"),
            reason=row.get("reason"),
            metadata=(
                row.get("metadata")
                if isinstance(row.get("metadata"), dict)
                else {}
            ),
            created_at=row.get("created_at"),
        )


@dataclass
class ApprovalRequest:
    """
    A recommendation put to a human.

    Approval is a domain object in its own right rather than a
    boolean on a simulation, which is what makes the history,
    the several attempts at the same decision, and the
    separation between agreeing and doing possible at all.
    """

    id: Optional[str]

    simulation_id: str

    simulation_option_id: str

    request_code: str

    title: str

    status: str = "pending"

    description: Optional[str] = None

    requested_by: str = "system"

    requested_at: Optional[str] = None

    reviewed_at: Optional[str] = None

    reviewed_by: Optional[str] = None

    review_reason: Optional[str] = None

    execution_started_at: Optional[str] = None

    execution_completed_at: Optional[str] = None

    execution_result: Dict[str, Any] = field(
        default_factory=dict
    )

    metadata: Dict[str, Any] = field(default_factory=dict)

    created_at: Optional[str] = None

    updated_at: Optional[str] = None

    # Populated on read, not stored.
    events: List[ApprovalEvent] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        from app.core.approval_rules import is_terminal

        return is_terminal(self.status)

    @property
    def can_execute(self) -> bool:
        """
        Only a prepared request may be executed.

        Mirrors the state machine rather than re-deriving it, so
        a change to the permitted transitions cannot leave this
        property quietly disagreeing with the rule that governs
        it.
        """

        return self.status == "ready_to_execute"

    @classmethod
    def from_row(
        cls, row: Dict[str, Any]
    ) -> "ApprovalRequest":
        return cls(
            id=row.get("id"),
            simulation_id=str(row.get("simulation_id")),
            simulation_option_id=str(
                row.get("simulation_option_id")
            ),
            request_code=row.get("request_code") or "",
            title=row.get("title") or "",
            status=row.get("status") or "pending",
            description=row.get("description"),
            requested_by=row.get("requested_by") or "system",
            requested_at=row.get("requested_at"),
            reviewed_at=row.get("reviewed_at"),
            reviewed_by=row.get("reviewed_by"),
            review_reason=row.get("review_reason"),
            execution_started_at=row.get(
                "execution_started_at"
            ),
            execution_completed_at=row.get(
                "execution_completed_at"
            ),
            execution_result=(
                row.get("execution_result")
                if isinstance(row.get("execution_result"), dict)
                else {}
            ),
            metadata=(
                row.get("metadata")
                if isinstance(row.get("metadata"), dict)
                else {}
            ),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )