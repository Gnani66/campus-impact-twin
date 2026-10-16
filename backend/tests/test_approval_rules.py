"""
Tests for Phase 11 approvals.

Two halves, and the second matters more than the first.

The state machine is pure and exhaustively tested, because it is
the safety property: a rejected action must never execute, and a
terminal decision must never be reopened.

The service is then tested against an in-memory repository, so
the whole workflow - raise, review, prepare, execute, audit - runs
without a database. If any of this passed only against a live
Supabase project it would be neither repeatable nor fast enough
to run on every change.
"""

import pytest

from app.core.approval_rules import (
    ALLOWED_TRANSITIONS,
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_EXECUTED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_READY_TO_EXECUTE,
    STATUS_REJECTED,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    ApprovalError,
    InvalidTransition,
    ReasonRequired,
    ReviewerRequired,
    UnknownStatus,
    can_transition,
    is_terminal,
    validate_review,
    validate_transition,
)
from app.models.approval import ApprovalEvent, ApprovalRequest
from app.schemas.approval import ApprovalCreate, ApprovalReview
from app.services.approval_service import (
    SIMULATED_EXECUTION_RESULT,
    ApprovalNotFound,
    ApprovalPersistenceError,
    ApprovalService,
)


# ============================================================
# THE SPECIFIED TRANSITIONS
# ============================================================


class TestSpecifiedTransitions:
    def test_pending_can_be_approved(self):
        validate_transition("pending", "approved")

    def test_pending_can_be_rejected(self):
        validate_transition("pending", "rejected")

    def test_approved_can_be_prepared(self):
        validate_transition("approved", "ready_to_execute")

    def test_ready_can_be_executed(self):
        validate_transition("ready_to_execute", "executed")

    def test_pending_can_expire(self):
        validate_transition("pending", "expired")

    def test_pending_can_be_cancelled(self):
        validate_transition("pending", "cancelled")


# ============================================================
# THE FORBIDDEN TRANSITIONS
# ============================================================
#
# Every one of these is a way an action could be applied without a
# human having authorised it, or a closed decision quietly
# reopened.


class TestForbiddenTransitions:
    @pytest.mark.parametrize(
        "current,requested",
        [
            ("rejected", "approved"),
            ("rejected", "executed"),
            ("rejected", "ready_to_execute"),
            ("pending", "executed"),
            ("pending", "ready_to_execute"),
            ("executed", "approved"),
            ("executed", "rejected"),
            ("executed", "ready_to_execute"),
            ("expired", "approved"),
            ("cancelled", "approved"),
            ("cancelled", "executed"),
        ],
    )
    def test_transition_is_refused(
        self, current, requested
    ):
        with pytest.raises(InvalidTransition):
            validate_transition(current, requested)

        assert (
            can_transition(current, requested) is False
        )

    def test_rejected_is_terminal(self):
        """
        The single most important property in the phase.
        """

        assert is_terminal(STATUS_REJECTED)

        with pytest.raises(InvalidTransition) as caught:
            validate_transition(STATUS_REJECTED, STATUS_EXECUTED)

        assert "closed" in str(caught.value)

    def test_executed_cannot_be_reopened(self):
        for target in VALID_STATUSES:
            assert not can_transition(
                STATUS_EXECUTED, target
            )

    def test_approval_does_not_imply_execution(self):
        """
        Agreeing and doing are separate boundaries. A frontend
        bug must not be able to skip the prepare step.
        """

        assert not can_transition(
            STATUS_APPROVED, STATUS_EXECUTED
        )

    def test_unknown_status_rejected(self):
        with pytest.raises(UnknownStatus):
            validate_transition("pending", "teleported")

        with pytest.raises(UnknownStatus):
            validate_transition("imaginary", "approved")

    def test_terminal_states_have_no_exits(self):
        for status in TERMINAL_STATUSES:
            assert (
                ALLOWED_TRANSITIONS[status] == frozenset()
            )


# ============================================================
# REVIEW VALIDATION
# ============================================================


class TestReviewValidation:
    def test_valid_approval(self):
        validate_review(
            "pending", "approved", "manager", "looks right"
        )

    def test_valid_rejection(self):
        validate_review(
            "pending", "rejected", "manager", "hall in use"
        )

    def test_reviewer_is_required(self):
        with pytest.raises(ReviewerRequired):
            validate_review("pending", "approved", "", "why")

        with pytest.raises(ReviewerRequired):
            validate_review("pending", "approved", None, "why")

        with pytest.raises(ReviewerRequired):
            validate_review(
                "pending", "approved", "   ", "why"
            )

    def test_reason_is_required_to_close(self):
        """
        A rejection with no explanation cannot be reviewed by
        anyone later, which makes the audit trail decorative.
        """

        with pytest.raises(ReasonRequired):
            validate_review(
                "pending", "rejected", "manager", None
            )

        with pytest.raises(ReasonRequired):
            validate_review(
                "pending", "rejected", "manager", "  "
            )

    def test_reason_is_optional_when_not_closing(self):
        validate_review(
            "pending", "expired", "scheduler", None
        )

    def test_transition_checked_before_reason(self):
        """
        A refusal of the transition is the more useful error.
        Checking the reason first would send a caller looking in
        the wrong place.
        """

        with pytest.raises(InvalidTransition):
            validate_review(
                "rejected", "approved", "manager", "because"
            )


class TestReviewSchema:
    def test_review_status_is_restricted(self):
        """
        A client cannot walk the state machine by naming a
        status like `executed` in a review.
        """

        with pytest.raises(Exception):
            ApprovalReview(
                status="executed", reviewer="manager"
            )

        with pytest.raises(Exception):
            ApprovalReview(
                status="ready_to_execute", reviewer="manager"
            )

    def test_review_accepts_approve_and_reject(self):
        assert (
            ApprovalReview(
                status="approved", reviewer="m"
            ).status
            == "approved"
        )
        assert (
            ApprovalReview(
                status="rejected", reviewer="m"
            ).status
            == "rejected"
        )

    def test_reviewer_is_required_by_the_schema(self):
        with pytest.raises(Exception):
            ApprovalReview(status="approved", reviewer="")

    def test_create_forbids_extra_fields(self):
        """
        An approval is a control boundary; a payload carrying
        fields the server does not understand is the shape of a
        confused-deputy request.
        """

        with pytest.raises(Exception):
            ApprovalCreate(
                simulation_id="s",
                simulation_option_id="o",
                title="t",
                status="approved",
            )

    def test_create_requires_a_title(self):
        with pytest.raises(Exception):
            ApprovalCreate(
                simulation_id="s",
                simulation_option_id="o",
                title="",
            )


# ============================================================
# SERVICE, AGAINST AN IN-MEMORY REPOSITORY
# ============================================================


class FakeRepository:
    """
    An in-memory stand-in with the same surface.

    Deliberately faithful about the one thing that matters: it
    stores what it is given without consulting the state machine,
    so any rule the service fails to enforce shows up here as a
    workflow that succeeds when it should not.
    """

    def __init__(self, run=None, options=None):
        self.requests = {}
        self.events = []

        self.simulations = run or {
            "id": "sim-1",
            "zone_code": "LH01",
            "status": "completed",
        }

        self.options = options if options is not None else [
            {
                "id": "opt-1",
                "feasible": True,
                "intervention": {"code": "HVAC_STANDBY"},
            }
        ]

        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1

        return f"row-{self._counter}"

    def create_request(self, payload):
        row = {
            **payload,
            "id": self._next_id(),
            "requested_at": "2026-10-16T12:00:00Z",
            "execution_result": {},
        }

        self.requests[row["id"]] = row

        return ApprovalRequest.from_row(row)

    def get_request(self, approval_id):
        row = self.requests.get(approval_id)

        return ApprovalRequest.from_row(row) if row else None

    def update_request(self, approval_id, changes):
        row = self.requests.get(approval_id)

        if row is None:
            return None

        row.update(changes)

        return ApprovalRequest.from_row(row)

    def create_event(self, payload):
        row = {
            **payload,
            "id": self._next_id(),
            "created_at": "2026-10-16T12:00:0"
            f"{len(self.events)}Z",
        }

        self.events.append(row)

        return ApprovalEvent.from_row(row)

    def list_events(self, approval_id):
        return [
            ApprovalEvent.from_row(row)
            for row in self.events
            if row["approval_request_id"] == approval_id
        ]

    def list_events_for(self, approval_ids):
        """
        Grouped histories for several requests at once, matching
        the real repository's one-query behaviour.
        """

        wanted = set(approval_ids)

        grouped = {item: [] for item in wanted}

        for row in self.events:
            request_id = row["approval_request_id"]

            if request_id in grouped:
                grouped[request_id].append(
                    ApprovalEvent.from_row(row)
                )

        return grouped

    def list_by_status(self, status, limit=50):
        return [
            ApprovalRequest.from_row(row)
            for row in self.requests.values()
            if row["status"] == status
        ][:limit]

    def list_all(self, limit=50):
        return [
            ApprovalRequest.from_row(row)
            for row in self.requests.values()
        ][:limit]

    # Simulation lookups the service performs directly.
    def _simulation_run(self, simulation_id):
        if self.simulations and self.simulations.get(
            "id"
        ) == simulation_id:
            return self.simulations

        return None


def _service(**kwargs):
    repository = FakeRepository(**kwargs)

    def loader(simulation_id):
        if repository.simulations and repository.simulations.get(
            "id"
        ) == simulation_id:
            return repository.simulations, repository.options

        return None, []

    return (
        ApprovalService(
            repository=repository,
            simulation_loader=loader,
        ),
        repository,
    )


def _create(service) -> ApprovalRequest:
    return service.create_approval(
        ApprovalCreate(
            simulation_id="sim-1",
            simulation_option_id="opt-1",
            title="Reduce lecture hall HVAC usage",
            description="Apply the standby optimisation.",
            requested_by="system",
        )
    )


class TestCreate:
    def test_creates_a_pending_request(self):
        service, _ = _service()

        approval = _create(service)

        assert approval.status == STATUS_PENDING
        assert approval.request_code.startswith("APR-")
        assert approval.requested_by == "system"

    def test_records_the_creation_event(self):
        service, repository = _service()

        approval = _create(service)

        assert len(repository.events) == 1
        assert repository.events[0]["new_status"] == (
            STATUS_PENDING
        )

    def test_request_codes_are_unique(self):
        service, _ = _service()

        codes = {
            _create(service).request_code
            for _ in range(10)
        }

        assert len(codes) == 10

    def test_unknown_simulation_is_refused(self):
        service, repository = _service()

        repository.simulations = None

        with pytest.raises(ApprovalNotFound):
            _create(service)

    def test_option_must_belong_to_the_simulation(self):
        service, repository = _service()

        repository.options = [
            {"id": "opt-OTHER", "feasible": True}
        ]

        with pytest.raises(ApprovalNotFound):
            _create(service)

    def test_infeasible_option_cannot_be_submitted(self):
        """
        Asking a manager to authorise something the engine has
        already refused is not a review, it is a rubber stamp.
        """

        service, repository = _service(
            options=[{"id": "opt-1", "feasible": False}]
        )

        with pytest.raises(ApprovalError):
            _create(service)


class TestReview:
    def test_approving(self):
        service, _ = _service()

        approval = _create(service)

        reviewed = service.review(
            approval.id,
            ApprovalReview(
                status="approved",
                reviewer="facility_manager",
                reason="Evidence is sufficient.",
            ),
        )

        assert reviewed.status == STATUS_APPROVED
        assert reviewed.reviewed_by == "facility_manager"

    def test_rejecting(self):
        service, _ = _service()

        approval = _create(service)

        reviewed = service.review(
            approval.id,
            ApprovalReview(
                status="rejected",
                reviewer="facility_manager",
                reason="Hall is booked shortly.",
            ),
        )

        assert reviewed.status == STATUS_REJECTED

    def test_review_requires_a_reviewer(self):
        service, _ = _service()

        approval = _create(service)

        with pytest.raises(ReviewerRequired):
            service.review(
                approval.id,
                ApprovalReview(
                    status="approved",
                    reviewer="   ",
                    reason="why",
                ),
            )

    def test_rejection_requires_a_reason(self):
        service, _ = _service()

        approval = _create(service)

        with pytest.raises(ReasonRequired):
            service.review(
                approval.id,
                ApprovalReview(
                    status="rejected", reviewer="manager"
                ),
            )

    def test_rejected_cannot_be_approved_afterwards(self):
        service, _ = _service()

        approval = _create(service)

        service.review(
            approval.id,
            ApprovalReview(
                status="rejected",
                reviewer="m",
                reason="not now",
            ),
        )

        with pytest.raises(InvalidTransition):
            service.review(
                approval.id,
                ApprovalReview(
                    status="approved",
                    reviewer="m",
                    reason="changed my mind",
                ),
            )

    def test_every_transition_is_recorded(self):
        service, repository = _service()

        approval = _create(service)

        service.review(
            approval.id,
            ApprovalReview(
                status="approved",
                reviewer="m",
                reason="yes",
            ),
        )

        assert [
            event["new_status"] for event in repository.events
        ] == [STATUS_PENDING, STATUS_APPROVED]


class TestPrepare:
    def test_approved_becomes_ready(self):
        service, _ = _service()

        approval = _create(service)

        service.review(
            approval.id,
            ApprovalReview(
                status="approved",
                reviewer="m",
                reason="yes",
            ),
        )

        prepared = service.prepare(approval.id, "scheduler")

        assert prepared.status == STATUS_READY_TO_EXECUTE

    def test_pending_cannot_be_prepared(self):
        """
        An unreviewed request must not reach ready.
        """

        service, _ = _service()

        approval = _create(service)

        with pytest.raises(InvalidTransition):
            service.prepare(approval.id, "scheduler")

    def test_rejected_cannot_be_prepared(self):
        service, _ = _service()

        approval = _create(service)

        service.review(
            approval.id,
            ApprovalReview(
                status="rejected",
                reviewer="m",
                reason="no",
            ),
        )

        with pytest.raises(InvalidTransition):
            service.prepare(approval.id, "scheduler")


class TestExecute:
    def _ready(self, service):
        approval = _create(service)

        service.review(
            approval.id,
            ApprovalReview(
                status="approved",
                reviewer="m",
                reason="yes",
            ),
        )

        service.prepare(approval.id, "scheduler")

        return approval

    def test_ready_executes_in_simulation(self):
        service, _ = _service()

        approval = self._ready(service)

        executed = service.execute(approval.id, "operator")

        assert executed.status == STATUS_EXECUTED

    def test_execution_is_simulated(self):
        """
        The recorded claim must be true. Nothing physical
        happens, and the result says so.
        """

        service, _ = _service()

        approval = self._ready(service)

        executed = service.execute(approval.id, "operator")

        result = executed.execution_result

        assert result["mode"] == "simulation"
        assert result["executed"] is True
        assert "No physical campus system" in result["message"]

    def test_pending_cannot_execute(self):
        service, _ = _service()

        approval = _create(service)

        with pytest.raises(InvalidTransition):
            service.execute(approval.id, "operator")

    def test_approved_cannot_execute_without_preparing(self):
        service, _ = _service()

        approval = _create(service)

        service.review(
            approval.id,
            ApprovalReview(
                status="approved",
                reviewer="m",
                reason="yes",
            ),
        )

        with pytest.raises(InvalidTransition):
            service.execute(approval.id, "operator")

    def test_rejected_cannot_execute(self):
        """
        The single most important safety property in the phase.
        """

        service, _ = _service()

        approval = _create(service)

        service.review(
            approval.id,
            ApprovalReview(
                status="rejected",
                reviewer="m",
                reason="no",
            ),
        )

        with pytest.raises(InvalidTransition):
            service.prepare(approval.id, "scheduler")

        with pytest.raises(InvalidTransition):
            service.execute(approval.id, "operator")

    def test_executed_cannot_be_reopened(self):
        service, _ = _service()

        approval = self._ready(service)

        service.execute(approval.id, "operator")

        with pytest.raises(InvalidTransition):
            service.execute(approval.id, "operator")

        with pytest.raises(InvalidTransition):
            service.review(
                approval.id,
                ApprovalReview(
                    status="rejected",
                    reviewer="m",
                    reason="undo",
                ),
            )

    def test_execution_is_recorded(self):
        service, repository = _service()

        approval = self._ready(service)

        service.execute(approval.id, "operator")

        statuses = [
            event["new_status"] for event in repository.events
        ]

        assert statuses == [
            STATUS_PENDING,
            STATUS_APPROVED,
            STATUS_READY_TO_EXECUTE,
            STATUS_EXECUTED,
        ]


class TestAuditTrail:
    def test_history_carries_actor_and_reason(self):
        service, _ = _service()

        approval = _create(service)

        service.review(
            approval.id,
            ApprovalReview(
                status="approved",
                reviewer="facility_manager",
                reason="Evidence is sufficient.",
            ),
        )

        events = service.get_approval(approval.id).events

        assert events[0].actor == "system"
        assert events[1].actor == "facility_manager"
        assert (
            events[1].reason == "Evidence is sufficient."
        )

    def test_history_is_append_only(self):
        """
        The repository exposes no way to modify or remove an
        event, so history cannot be quietly rewritten.
        """

        service, repository = _service()

        approval = _create(service)

        service.review(
            approval.id,
            ApprovalReview(
                status="approved",
                reviewer="m",
                reason="yes",
            ),
        )

        for name in dir(repository):
            assert not name.startswith(
                ("delete", "update_event", "purge")
            )

    def test_pending_queue_lists_only_pending(self):
        service, _ = _service()

        first = _create(service)
        second = _create(service)

        service.review(
            first.id,
            ApprovalReview(
                status="approved",
                reviewer="m",
                reason="yes",
            ),
        )

        pending = service.pending()

        assert len(pending) == 1
        assert pending[0].id == second.id

    def test_missing_approval_is_reported(self):
        service, _ = _service()

        with pytest.raises(ApprovalNotFound):
            service.get_approval("nope")


# ============================================================
# TRUST BOUNDARY
# ============================================================


class TestTrustBoundary:
    def test_approval_code_cannot_actuate_anything(self):
        """
        No module under app/ may reach a campus system, so the
        recorded claim that nothing physical changed is true by
        construction rather than by intention.
        """

        import pathlib

        forbidden = (
            "requests.post",
            "paho",
            "mqtt_client.publish",
            "subprocess",
            "os.system",
            "socket.connect",
            "modbus",
        )

        offenders = []

        for path in pathlib.Path("app").rglob("*.py"):
            text = path.read_text()

            for token in forbidden:
                if token in text:
                    offenders.append(f"{path}: {token}")

        assert offenders == []

    def test_execution_result_cannot_be_configured(self):
        """
        The simulated wording is a module constant, not a
        parameter, so no caller can substitute a result that
        claims something real happened.
        """

        assert (
            SIMULATED_EXECUTION_RESULT["mode"]
            == "simulation"
        )

        import inspect

        from app.services.approval_service import (
            ApprovalService as Service,
        )

        signature = inspect.signature(Service.execute)

        assert list(signature.parameters) == [
            "self",
            "approval_id",
            "actor",
        ]