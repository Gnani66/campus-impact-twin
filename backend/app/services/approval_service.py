"""
Approval service (Phase 11).

The control boundary. This is the only place in the project
where a recommendation becomes an authorised action, and the
only place where a status changes.

Every mutation follows the same shape: validate the transition
against the state machine, write the new state, append an event.
The event is written after the state so that a failure between
the two leaves a request that is conservatively behind rather
than one that claims a decision nobody can find.

Execution here is SIMULATED and always will be for this
deployment. The service holds no client for any campus system
and imports nothing that could reach one, so there is no code
path from an approval to a physical actuator. That is asserted
by a test rather than left as a convention.
"""

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.approval_rules import (
    STATUS_APPROVED,
    STATUS_EXECUTED,
    STATUS_PENDING,
    STATUS_READY_TO_EXECUTE,
    ApprovalError,
    InvalidTransition,
    ReviewerRequired,
    ReasonRequired,
    UnknownStatus,
    validate_review,
    validate_transition,
)
from app.models.approval import (
    ApprovalEvent,
    ApprovalRequest,
)
from app.repositories.approval_repository import (
    ApprovalRepository,
)
from app.schemas.approval import (
    ApprovalCreate,
    ApprovalReview,
)


logger = logging.getLogger(__name__)


# The result of a simulated execution. Fixed wording, because it
# is a claim about what did and did not happen and will be shown
# to a user.
SIMULATED_EXECUTION_RESULT: Dict[str, Any] = {
    "mode": "simulation",
    "executed": True,
    "message": (
        "Action simulated successfully. No physical campus "
        "system was modified."
    ),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalNotFound(Exception):
    """No approval request with that id."""


class ApprovalPersistenceError(Exception):
    """
    The state change could not be recorded.

    Raised rather than swallowed. Losing an approval decision
    silently would mean an action exists that nobody can account
    for, which is the one outcome this whole phase exists to
    prevent.
    """


def _default_run_loader(simulation_id: str):
    """Reads a simulation and its options from storage."""

    from app.repositories.simulation_repository import (
        get_options,
        get_run,
    )

    return get_run(simulation_id), get_options(simulation_id)


class ApprovalService:
    """
    Creates, reviews and executes approval requests.
    """

    def __init__(
        self,
        repository: Optional[ApprovalRepository] = None,
        simulation_loader=None,
    ):
        self.repository = repository or ApprovalRepository()

        # Injected so the workflow can be exercised end to end
        # without a database. The default reaches the real
        # repositories; a test substitutes its own.
        self._simulation_loader = (
            simulation_loader or _default_run_loader
        )

    # ------------------------------------------------------
    # Creation
    # ------------------------------------------------------

    def create_approval(
        self, data: ApprovalCreate
    ) -> ApprovalRequest:
        """
        Puts a simulation option to a human.

        Refuses to raise a request for a simulation that did not
        complete. An approval for a blocked or refused simulation
        would put a decision to a manager that has no evidence
        behind it.
        """

        stored = self._load_simulation_option(
            data.simulation_id, data.simulation_option_id
        )

        code = self._generate_request_code()

        approval = self.repository.create_request(
            {
                "simulation_id": data.simulation_id,
                "simulation_option_id": (
                    data.simulation_option_id
                ),
                "request_code": code,
                "title": data.title,
                "description": data.description,
                "requested_by": data.requested_by,
                "status": STATUS_PENDING,
                "metadata": data.metadata,
            }
        )

        if approval is None:
            raise ApprovalPersistenceError(
                "The approval request could not be stored"
            )

        self._record_event(
            approval.id,
            previous_status=None,
            new_status=STATUS_PENDING,
            actor=data.requested_by,
            reason=(
                "Request raised for review of a simulated "
                "intervention."
            ),
            metadata={
                "simulation_id": data.simulation_id,
                "simulation_option_id": (
                    data.simulation_option_id
                ),
                "zone_code": stored.get("zone_code"),
            },
        )

        logger.info(
            "Approval %s raised by %s for simulation %s",
            code,
            data.requested_by,
            data.simulation_id,
        )

        return self.get_approval(approval.id)

    # ------------------------------------------------------
    # Reading
    # ------------------------------------------------------

    def get_approval(
        self, approval_id: str, with_events: bool = True
    ) -> ApprovalRequest:
        """One request, with its history."""

        approval = self.repository.get_request(approval_id)

        if approval is None:
            raise ApprovalNotFound(
                f"No approval request with id {approval_id}"
            )

        if with_events:
            approval.events = self.repository.list_events(
                approval_id
            )

        return approval

    def pending(self, limit: int = 50) -> List[ApprovalRequest]:
        """
        The review queue.

        This is what a dashboard's "needs approval" panel reads,
        and it is the only listing that represents unfinished
        business.

        Events are attached here, not only on the single-request
        path. The whole point of an approval queue is that each
        item is auditable at a glance; a list whose items carry an
        empty history makes the reviewer click through to
        `/approvals/{id}` to discover that something already
        happened to it.
        """

        requests = self.repository.list_by_status(
            STATUS_PENDING, limit=limit
        )

        return self._attach_events(requests)

    def all_requests(
        self, limit: int = 50
    ) -> List[ApprovalRequest]:
        """
        Every request, newest first, for the audit view.

        Carries the same histories as the queue: this listing is
        read to check what was done, and an audit trail that is
        empty in the view and full in the detail is not much of an
        audit trail.
        """

        requests = self.repository.list_all(limit=limit)

        return self._attach_events(requests)

    def _attach_events(
        self,
        requests: List[ApprovalRequest],
    ) -> List[ApprovalRequest]:
        """
        Fills in each request's history from a single query.

        A failure here must not lose the queue. The requests are
        returned with empty histories and the reason logged, because
        a list of requests without their history is still useful and
        a raised exception would take the approval workflow down
        with an unrelated read.
        """

        if not requests:
            return requests

        histories = self.repository.list_events_for(
            [request.id for request in requests if request.id]
        )

        for request in requests:
            request.events = histories.get(request.id, [])

        return requests

    # ------------------------------------------------------
    # Review
    # ------------------------------------------------------

    def review(
        self,
        approval_id: str,
        review: ApprovalReview,
    ) -> ApprovalRequest:
        """
        Records a human decision.

        Approving does not authorise execution on its own. That
        is a deliberate second boundary, so that the agreement
        and the doing are separately auditable.
        """

        approval = self._require(approval_id)

        validate_review(
            approval.status,
            review.status,
            review.reviewer,
            review.reason,
        )

        updated = self.repository.update_request(
            approval_id,
            {
                "status": review.status,
                "reviewed_at": _now_iso(),
                "reviewed_by": review.reviewer,
                "review_reason": review.reason,
            },
        )

        if updated is None:
            raise ApprovalPersistenceError(
                "The review could not be stored"
            )

        self._record_event(
            approval_id,
            previous_status=approval.status,
            new_status=review.status,
            actor=review.reviewer,
            reason=review.reason,
        )

        logger.info(
            "Approval %s %s by %s",
            approval.request_code,
            review.status,
            review.reviewer,
        )

        return self.get_approval(approval_id)

    # ------------------------------------------------------
    # Prepare
    # ------------------------------------------------------

    def prepare(
        self, approval_id: str, actor: str
    ) -> ApprovalRequest:
        """
        Marks an approved action ready to execute.

        Exists so that everything which should happen between
        agreement and execution - checking the world has not
        changed, scheduling the work - happens after a human has
        agreed and before anything runs.
        """

        approval = self._require(approval_id)

        validate_transition(
            approval.status, STATUS_READY_TO_EXECUTE
        )

        updated = self.repository.update_request(
            approval_id,
            {
                "status": STATUS_READY_TO_EXECUTE,
                "execution_started_at": None,
            },
        )

        if updated is None:
            raise ApprovalPersistenceError(
                "The prepare step could not be stored"
            )

        self._record_event(
            approval_id,
            previous_status=approval.status,
            new_status=STATUS_READY_TO_EXECUTE,
            actor=actor,
            reason=(
                "Preconditions checked; the action is cleared "
                "for simulated execution."
            ),
        )

        return self.get_approval(approval_id)

    # ------------------------------------------------------
    # Execute (simulated)
    # ------------------------------------------------------

    def execute(
        self, approval_id: str, actor: str
    ) -> ApprovalRequest:
        """
        Records a SIMULATED execution.

        Nothing physical happens. There is no client for any
        campus system in this process and nothing imported that
        could provide one, so the claim written into the result
        is true by construction rather than by promise.
        """

        approval = self._require(approval_id)

        # Raises for a rejected, cancelled, expired, already
        # executed, or merely pending request.
        validate_transition(approval.status, STATUS_EXECUTED)

        completed = _now_iso()

        updated = self.repository.update_request(
            approval_id,
            {
                "status": STATUS_EXECUTED,
                "execution_completed_at": completed,
                "execution_result": {
                    **SIMULATED_EXECUTION_RESULT,
                    "simulation_id": approval.simulation_id,
                    "simulation_option_id": (
                        approval.simulation_option_id
                    ),
                },
            },
        )

        if updated is None:
            raise ApprovalPersistenceError(
                "The execution could not be stored"
            )

        self._record_event(
            approval_id,
            previous_status=approval.status,
            new_status=STATUS_EXECUTED,
            actor=actor,
            reason=(
                "Simulated execution completed. No physical "
                "campus system was modified."
            ),
            metadata=dict(SIMULATED_EXECUTION_RESULT),
        )

        logger.info(
            "Approval %s executed in simulation mode by %s",
            approval.request_code,
            actor,
        )

        return self.get_approval(approval_id)

    # ------------------------------------------------------
    # Internals
    # ------------------------------------------------------

    def _require(self, approval_id: str) -> ApprovalRequest:
        approval = self.repository.get_request(approval_id)

        if approval is None:
            raise ApprovalNotFound(
                f"No approval request with id {approval_id}"
            )

        return approval

    def _record_event(
        self,
        approval_id: str,
        previous_status: Optional[str],
        new_status: str,
        actor: str,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApprovalEvent:
        """
        Appends one history entry.

        A failure to record history is logged and swallowed:
        the state change has already happened, and refusing to
        acknowledge it would leave the caller believing an
        approval was NOT made when it was. The gap is visible in
        the logs and in the absence of an event.
        """

        event = self.repository.create_event(
            {
                "approval_request_id": approval_id,
                "previous_status": previous_status,
                "new_status": new_status,
                "actor": actor,
                "reason": reason,
                "metadata": metadata or {},
            }
        )

        if event is None:
            logger.error(
                "Approval %s changed to '%s' but the history "
                "entry could not be written",
                approval_id,
                new_status,
            )

        return event

    def _load_simulation_option(
        self, simulation_id: str, option_id: str
    ) -> Dict[str, Any]:
        """
        Confirms the option belongs to the simulation.

        Read for the zone and for its feasibility, not merely to
        confirm existence. An approval raised for an infeasible
        option is asking a manager to authorise something the
        engine already refused, and the request should not exist.
        """

        run, options = self._simulation_loader(simulation_id)

        if run is None:
            raise ApprovalNotFound(
                f"No simulation run with id {simulation_id}"
            )

        match = None

        for option in options:
            if str(option.get("id")) == str(option_id):
                match = option
                break

        if match is None:
            raise ApprovalNotFound(
                "That option does not belong to this "
                "simulation"
            )

        if not match.get("feasible", False):
            raise ApprovalError(
                "That option was rejected by the engine as "
                "infeasible, so it cannot be submitted for "
                "approval."
            )

        return {
            "zone_code": run.get("zone_code"),
            "status": run.get("status"),
            "option": match,
        }

    @staticmethod
    def _generate_request_code() -> str:
        """
        A human-quotable reference.

        Request codes get read aloud and copied into tickets, so
        they use an unambiguous alphabet: no O/0 or I/1.
        """

        token = secrets.token_hex(3).upper()

        return f"APR-{token}"


approval_service = ApprovalService()