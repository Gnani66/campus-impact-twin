"""
Approval rules (Phase 11).

The state machine that stands between "the system recommends
something" and "a human authorises it".

This module is deliberately the smallest and most boring file in
the project, because it is the one that has to be right. Every
transition the system permits is written out explicitly; nothing
is inferred, and there is no wildcard path from one state to
another. A frontend bug cannot become a business-logic bug
because a frontend bug has to ask this module for permission
first.

Two properties matter more than convenience:

* Terminal states are terminal. A rejected, expired, cancelled or
  executed request has no outgoing transitions, so reopening a
  closed decision is not merely discouraged but impossible
  without editing the database by hand.

* Every decision records who and why. A transition with no actor
  is not a decision, it is a state change.
"""

from typing import Dict, FrozenSet, Optional


# ============================================================
# STATES
# ============================================================

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
STATUS_READY_TO_EXECUTE = "ready_to_execute"
STATUS_EXECUTED = "executed"

VALID_STATUSES: FrozenSet[str] = frozenset(
    {
        STATUS_PENDING,
        STATUS_APPROVED,
        STATUS_REJECTED,
        STATUS_EXPIRED,
        STATUS_CANCELLED,
        STATUS_READY_TO_EXECUTE,
        STATUS_EXECUTED,
    }
)


# ============================================================
# TRANSITIONS
# ============================================================
#
# Written out in full rather than derived. The cost is a few
# lines; the benefit is that the permitted behaviour of a control
# boundary can be read in one glance and audited against the
# specification without executing anything.

ALLOWED_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    STATUS_PENDING: frozenset(
        {
            STATUS_APPROVED,
            STATUS_REJECTED,
            STATUS_EXPIRED,
            STATUS_CANCELLED,
        }
    ),
    # Approval deliberately does NOT imply execution. A separate
    # prepare step exists so that scheduling the work, checking
    # preconditions and confirming the world has not changed all
    # happen after a human has agreed to it but before anything
    # runs.
    STATUS_APPROVED: frozenset(
        {STATUS_READY_TO_EXECUTE, STATUS_CANCELLED}
    ),
    STATUS_READY_TO_EXECUTE: frozenset(
        {STATUS_EXECUTED, STATUS_CANCELLED}
    ),
    # Terminal.
    STATUS_REJECTED: frozenset(),
    STATUS_EXPIRED: frozenset(),
    STATUS_CANCELLED: frozenset(),
    STATUS_EXECUTED: frozenset(),
}


TERMINAL_STATUSES: FrozenSet[str] = frozenset(
    {
        STATUS_REJECTED,
        STATUS_EXPIRED,
        STATUS_CANCELLED,
        STATUS_EXECUTED,
    }
)


# What a reviewer may decide from the pending queue. Restricted
# so that a crafted payload cannot approve an action by naming a
# status like `executed`.
REVIEWABLE_STATUSES: FrozenSet[str] = frozenset(
    {
        STATUS_APPROVED,
        STATUS_REJECTED,
    }
)


# ============================================================
# ERRORS
# ============================================================


class ApprovalError(Exception):
    """Base for every approval rule violation."""


class InvalidTransition(ApprovalError):
    """
    The requested move is not permitted from the current state.

    Carries both states so a caller can explain the refusal
    rather than reporting a generic failure.
    """

    def __init__(
        self, current: str, requested: str, reason: str = ""
    ):
        self.current = current
        self.requested = requested
        self.reason = reason

        message = (
            f"Cannot move an approval from '{current}' to "
            f"'{requested}'."
        )

        if reason:
            message = f"{message} {reason}"

        super().__init__(message)


class UnknownStatus(ApprovalError):
    """A status outside the defined set was supplied."""


class ReviewerRequired(ApprovalError):
    """A review was attempted without naming a reviewer."""


class ReasonRequired(ApprovalError):
    """
    A reason is mandatory for a decision that closes a request.

    A rejection with no reason is not reviewable later: nobody
    can reconstruct why an action was refused, which makes the
    audit trail decorative rather than useful.
    """


# ============================================================
# VALIDATION
# ============================================================


def validate_transition(
    current: str, requested: str
) -> None:
    """
    Permits a move, or raises.

    Raises rather than returning False so that a caller cannot
    forget to check the result. Every code path that changes
    state goes through this function, so forgetting is the only
    failure mode and raising removes it.
    """

    if current not in VALID_STATUSES:
        raise UnknownStatus(
            f"'{current}' is not a known approval status."
        )

    if requested not in VALID_STATUSES:
        raise UnknownStatus(
            f"'{requested}' is not a known approval status."
        )

    permitted = ALLOWED_TRANSITIONS.get(current, frozenset())

    if requested not in permitted:
        if current in TERMINAL_STATUSES:
            raise InvalidTransition(
                current,
                requested,
                reason=(
                    "This request is closed and cannot be "
                    "reopened."
                ),
            )

        raise InvalidTransition(
            current, requested
        )


def can_transition(current: str, requested: str) -> bool:
    """The same question, answered without raising."""

    try:
        validate_transition(current, requested)

        return True
    except ApprovalError:
        return False


def validate_review(
    current: str,
    status: str,
    reviewer: Optional[str],
    reason: Optional[str] = None,
) -> None:
    """
    Validates a human decision.

    A reviewer is always required. A reason is required for any
    decision that closes the request, and optional when it does
    not.
    """

    validate_transition(current, status)

    if not reviewer or not str(reviewer).strip():
        raise ReviewerRequired(
            "A review must name the person making it."
        )

    closes = status in (
        STATUS_APPROVED,
        STATUS_REJECTED,
        STATUS_CANCELLED,
    )

    if closes and (
        not reason or not str(reason).strip()
    ):
        raise ReasonRequired(
            f"A '{status}' decision must include a reason."
        )


def is_terminal(status: str) -> bool:
    """Whether a status admits no further transitions."""

    return status in TERMINAL_STATUSES