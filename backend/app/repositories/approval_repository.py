"""
Approval repository.

All SQL for Phase 11 lives here, against Supabase over
PostgREST. The specification sketches a SQLAlchemy repository
with a session; this project has no declarative base and no
engine, so the same operations are expressed through the shared
client. Every service in this project reaches storage this way,
and a second mechanism would mean a second set of failure modes.

Events are never updated or deleted. There is no method here
that could: the history is append-only by construction rather
than by convention.
"""

import logging
from typing import Any, Dict, List, Optional

from app.db.supabase import get_supabase
from app.models.approval import (
    ApprovalEvent,
    ApprovalRequest,
)


logger = logging.getLogger(__name__)


REQUESTS_TABLE = "approval_requests"
EVENTS_TABLE = "approval_events"

REQUEST_COLUMNS = (
    "id,simulation_id,simulation_option_id,request_code,"
    "title,description,requested_by,status,requested_at,"
    "reviewed_at,reviewed_by,review_reason,"
    "execution_started_at,execution_completed_at,"
    "execution_result,metadata,created_at,updated_at"
)


class ApprovalRepository:
    """
    Persistence for approval requests and their history.
    """

    def __init__(self, client=None):
        # Accepting a client keeps the class testable without a
        # database; production passes None and gets the shared
        # Supabase client per call.
        self._client = client

    def _db(self):
        return self._client or get_supabase()

    # ------------------------------------------------------
    # Requests
    # ------------------------------------------------------

    def create_request(
        self, payload: Dict[str, Any]
    ) -> Optional[ApprovalRequest]:
        try:
            result = (
                self._db()
                .table(REQUESTS_TABLE)
                .insert(payload)
                .execute()
                .data
            )
        except Exception:
            logger.exception(
                "Failed to create an approval request"
            )

            return None

        if not result:
            return None

        return ApprovalRequest.from_row(result[0])

    def get_request(
        self, approval_id: str
    ) -> Optional[ApprovalRequest]:
        try:
            result = (
                self._db()
                .table(REQUESTS_TABLE)
                .select(REQUEST_COLUMNS)
                .eq("id", approval_id)
                .limit(1)
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read approval request %s",
                approval_id,
            )

            return None

        rows = result.data or []

        return (
            ApprovalRequest.from_row(rows[0]) if rows else None
        )

    def list_by_status(
        self,
        status: str,
        limit: int = 50,
    ) -> List[ApprovalRequest]:
        """
        The queue for a given status, oldest first.

        Oldest first because a pending queue is a work queue, and
        a manager should see the request that has been waiting
        longest.
        """

        try:
            result = (
                self._db()
                .table(REQUESTS_TABLE)
                .select(REQUEST_COLUMNS)
                .eq("status", status)
                .order("created_at")
                .limit(max(1, min(limit, 200)))
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to list approvals with status '%s'",
                status,
            )

            return []

        return [
            ApprovalRequest.from_row(row)
            for row in (result.data or [])
        ]

    def list_all(
        self, limit: int = 50
    ) -> List[ApprovalRequest]:
        try:
            result = (
                self._db()
                .table(REQUESTS_TABLE)
                .select(REQUEST_COLUMNS)
                .order("created_at", desc=True)
                .limit(max(1, min(limit, 200)))
                .execute()
            )
        except Exception:
            logger.exception("Failed to list approvals")

            return []

        return [
            ApprovalRequest.from_row(row)
            for row in (result.data or [])
        ]

    def update_request(
        self,
        approval_id: str,
        changes: Dict[str, Any],
    ) -> Optional[ApprovalRequest]:
        try:
            result = (
                self._db()
                .table(REQUESTS_TABLE)
                .update(changes)
                .eq("id", approval_id)
                .select(REQUEST_COLUMNS)
                .execute()
                .data
            )
        except Exception:
            logger.exception(
                "Failed to update approval request %s",
                approval_id,
            )

            return None

        if not result:
            return None

        return ApprovalRequest.from_row(result[0])

    # ------------------------------------------------------
    # Events
    # ------------------------------------------------------

    def create_event(
        self, payload: Dict[str, Any]
    ) -> Optional[ApprovalEvent]:
        """
        Appends one entry to the history.

        The only write method for events. Nothing here updates or
        removes one.
        """

        try:
            result = (
                self._db()
                .table(EVENTS_TABLE)
                .insert(payload)
                .execute()
                .data
            )
        except Exception:
            logger.exception(
                "Failed to record an approval event"
            )

            return None

        if not result:
            return None

        return ApprovalEvent.from_row(result[0])

    def list_events(
        self, approval_id: str
    ) -> List[ApprovalEvent]:
        """The full history, oldest first."""

        try:
            result = (
                self._db()
                .table(EVENTS_TABLE)
                .select(
                    "id,approval_request_id,previous_status,"
                    "new_status,actor,reason,metadata,created_at"
                )
                .eq("approval_request_id", approval_id)
                .order("created_at")
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read events for approval %s",
                approval_id,
            )

            return []

        return [
            ApprovalEvent.from_row(row)
            for row in (result.data or [])
        ]
    def list_events_for(
        self,
        approval_ids: List[str],
    ) -> Dict[str, List[ApprovalEvent]]:
        """
        Histories for several requests in one query.

        A listing that fetched events per row would issue a query
        per request, and the audit view is exactly the page that
        shows a queue rather than one item. One query, grouped by
        request, keeps the listing proportional.

        Returns a mapping with an empty list for any request that has
        no events, so a caller never has to distinguish "no such
        request" from "no history yet".
        """

        wanted = [str(item) for item in approval_ids if item]

        grouped: Dict[str, List[ApprovalEvent]] = {
            approval_id: [] for approval_id in wanted
        }

        if not wanted:
            return grouped

        try:
            result = (
                self._db()
                .table(EVENTS_TABLE)
                .select(
                    "id,approval_request_id,previous_status,"
                    "new_status,actor,reason,metadata,created_at"
                )
                .in_("approval_request_id", wanted)
                .order("created_at")
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read events for %d approvals",
                len(wanted),
            )

            return grouped

        for row in result.data or []:
            request_id = row.get("approval_request_id")

            if request_id in grouped:
                grouped[request_id].append(
                    ApprovalEvent.from_row(row)
                )

        return grouped
