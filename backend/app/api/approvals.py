"""
Approval API (Phase 11).

The control boundary as an HTTP surface.

Two rules govern every handler here. Rule violations are
reported to the caller precisely, because a caller needs to know
*which* transition was refused; and internal failures return a
fixed message with the traceback in the log, because an approval
is a record about a decision and a database error has no place
in it.
"""

import logging
from typing import Optional

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.core.approval_rules import (
    ApprovalError,
    InvalidTransition,
    ReasonRequired,
    ReviewerRequired,
    UnknownStatus,
)
from app.models.approval import ApprovalEvent, ApprovalRequest
from app.schemas.approval import (
    ApprovalCreate,
    ApprovalEventResponse,
    ApprovalExecutionResponse,
    ApprovalResponse,
    ApprovalReview,
    ApprovalReviewResponse,
)
from app.services.approval_service import (
    ApprovalNotFound,
    ApprovalPersistenceError,
    ApprovalService,
    approval_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/approvals",
    tags=["Approvals"],
)


FAULT_DETAIL = "The approval request could not be processed."


def _to_response(approval: ApprovalRequest) -> ApprovalResponse:
    return ApprovalResponse(
        id=approval.id,
        request_code=approval.request_code,
        simulation_id=approval.simulation_id,
        simulation_option_id=approval.simulation_option_id,
        title=approval.title,
        status=approval.status,
        description=approval.description,
        requested_by=approval.requested_by,
        requested_at=approval.requested_at,
        reviewed_at=approval.reviewed_at,
        reviewed_by=approval.reviewed_by,
        review_reason=approval.review_reason,
        execution_started_at=approval.execution_started_at,
        execution_completed_at=approval.execution_completed_at,
        execution_result=approval.execution_result,
        metadata=approval.metadata,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
        events=[
            ApprovalEventResponse(
                id=event.id,
                previous_status=event.previous_status,
                new_status=event.new_status,
                actor=event.actor,
                reason=event.reason,
                metadata=event.metadata,
                created_at=event.created_at,
            )
            for event in approval.events
        ],
    )


def _to_event_response(
    event: Optional[ApprovalEvent],
) -> Optional[ApprovalEventResponse]:
    if event is None:
        return None

    return ApprovalEventResponse(
        id=event.id,
        previous_status=event.previous_status,
        new_status=event.new_status,
        actor=event.actor,
        reason=event.reason,
        metadata=event.metadata,
        created_at=event.created_at,
    )


def _fail(error: Exception) -> HTTPException:
    """
    Maps a rule violation onto a precise HTTP response.

    A refused transition is a 409, not a 400: the request was
    well formed, it conflicts with the resource's current state.
    Collapsing the two would tell a frontend to fix its payload
    when in fact it must not proceed.
    """

    if isinstance(error, ApprovalNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        )

    if isinstance(error, UnknownStatus):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )

    if isinstance(error, (ReviewerRequired, ReasonRequired)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        )

    if isinstance(error, InvalidTransition):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )

    if isinstance(error, ApprovalError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )

    if isinstance(error, ApprovalPersistenceError):
        return HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        )

    logger.exception(
        "Unexpected approval failure: %s", type(error).__name__
    )

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=FAULT_DETAIL,
    )


# ============================================================
# ROUTES
# ============================================================


@router.post(
    "",
    response_model=ApprovalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a simulated intervention for approval",
)
def create_approval(data: ApprovalCreate):
    """
    Creates a pending request.

    Refuses an option the engine already rejected as infeasible:
    putting that to a manager would ask them to authorise
    something the engine has already refused.
    """

    try:
        approval = approval_service.create_approval(data)

        return _to_response(approval)

    except Exception as exc:
        raise _fail(exc) from exc


@router.get(
    "/pending",
    response_model=list[ApprovalResponse],
    summary="The approval queue",
)
def list_pending(
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    Requests awaiting a human decision.

    This is the endpoint a dashboard's "needs approval" panel
    reads. Oldest first, because it is a work queue.
    """

    try:
        return [
            _to_response(approval)
            for approval in approval_service.pending(limit=limit)
        ]

    except Exception as exc:
        raise _fail(exc) from exc


@router.get(
    "",
    response_model=list[ApprovalResponse],
    summary="Every approval request, newest first",
)
def list_approvals(
    limit: int = Query(default=50, ge=1, le=200),
):
    """The audit view across all requests."""

    try:
        return [
            _to_response(approval)
            for approval in approval_service.all_requests(
                limit=limit
            )
        ]

    except Exception as exc:
        raise _fail(exc) from exc


@router.get(
    "/{approval_id}",
    response_model=ApprovalResponse,
    summary="One approval request with its history",
)
def get_approval(approval_id: str):
    try:
        approval = approval_service.get_approval(approval_id)

        return _to_response(approval)

    except Exception as exc:
        raise _fail(exc) from exc


@router.get(
    "/{approval_id}/events",
    response_model=list[ApprovalEventResponse],
    summary="The immutable history of one request",
)
def get_events(approval_id: str):
    """
    Every transition, in order, with its actor and reason.

    Append-only. This is the audit trail Phase 14 will build a
    decision passport on, which is why it is a separate read
    rather than something buried in the approval response.
    """

    try:
        approval = approval_service.get_approval(approval_id)

        return [
            ApprovalEventResponse(
                id=event.id,
                previous_status=event.previous_status,
                new_status=event.new_status,
                actor=event.actor,
                reason=event.reason,
                metadata=event.metadata,
                created_at=event.created_at,
            )
            for event in approval.events
        ]

    except Exception as exc:
        raise _fail(exc) from exc


@router.post(
    "/{approval_id}/review",
    response_model=ApprovalReviewResponse,
    summary="Approve or reject a request",
)
def review_approval(
    approval_id: str, review: ApprovalReview
):
    """
    Records a human decision.

    A reviewer is always required. A reason is required for
    anything that closes the request, because a rejection with no
    explanation cannot be reviewed by anyone later.
    """

    try:
        approval = approval_service.review(approval_id, review)

        events = approval.events or []

        return ApprovalReviewResponse(
            approval=_to_response(approval),
            event=_to_event_response(
                events[-1] if events else None
            ),
        )

    except Exception as exc:
        raise _fail(exc) from exc


@router.post(
    "/{approval_id}/prepare",
    response_model=ApprovalResponse,
    summary="Clear an approved action for execution",
)
def prepare_approval(
    approval_id: str,
    actor: str = Query(min_length=1, max_length=100),
):
    """
    Moves an approved request to ready.

    A deliberate second boundary: agreeing and doing are separate
    steps, separately signed, so the moment of authorisation is
    not the moment of action.
    """

    try:
        approval = approval_service.prepare(approval_id, actor)

        return _to_response(approval)

    except Exception as exc:
        raise _fail(exc) from exc


@router.post(
    "/{approval_id}/execute",
    response_model=ApprovalExecutionResponse,
    summary="Record a SIMULATED execution",
)
def execute_approval(
    approval_id: str,
    actor: str = Query(min_length=1, max_length=100),
):
    """
    Records a simulated execution.

    No physical campus system is modified. There is no client for
    one in this process, so the recorded result is true by
    construction rather than by intention.

    Permitted only from `ready_to_execute`. A pending, rejected
    or already-executed request is refused with 409.
    """

    try:
        approval = approval_service.execute(approval_id, actor)

        events = approval.events or []

        return ApprovalExecutionResponse(
            approval=_to_response(approval),
            event=_to_event_response(
                events[-1] if events else None
            ),
            execution_result=approval.execution_result,
        )

    except Exception as exc:
        raise _fail(exc) from exc