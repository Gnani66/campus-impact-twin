"""
Digital twin repository.

Reads only. The twin is a view over data this project already
stores, never a second copy of it.

That rule is what stops the twin from drifting. A separate
telemetry table would eventually disagree with
`telemetry_readings`, and the 3D view would then be showing
something the operational engine does not believe. Every read here
degrades to empty rather than raising: a zone with no readings is
a zone reporting nothing, which the status rules turn into
OFFLINE, and that is a legitimate answer.
"""

import logging
from typing import Any, Dict, List, Optional

from app.db.supabase import get_supabase


logger = logging.getLogger(__name__)


ZONES = "zones"
TELEMETRY = "telemetry_readings"
OBSERVATIONS = "observations"
INCIDENTS = "incidents"
CORRELATION_RUNS = "correlation_runs"
APPROVALS = "approval_requests"


def _num(value) -> Optional[float]:
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return None if number != number else number


class DigitalTwinRepository:
    """
    Aggregates the existing campus record.
    """

    def __init__(self, client=None):
        self._client = client

    def _db(self):
        return self._client or get_supabase()

    # ------------------------------------------------------
    # Zones
    # ------------------------------------------------------

    def zones(self, campus_code: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Every zone, with the identity the twin needs.

        `twin_model_object` is the database's own hook for which
        object inside the GLB an entity maps to, so the mapping
        lives with the zone rather than in frontend code.
        """

        try:
            query = (
                self._db()
                .table(ZONES)
                .select(
                    "id,code,name,zone_type,capacity,"
                    "twin_model_object,metadata"
                )
            )

            if campus_code:
                # Resolved through the building, so a campus code
                # narrows without duplicating the hierarchy.
                query = query.eq(
                    "id",
                    self._first_zone_id_for_campus(campus_code)
                )

            result = query.order("code").execute()
        except Exception:
            logger.exception("Failed to read zones for the twin")

            return []

        return result.data or []

    def _first_zone_id_for_campus(
        self, campus_code: str
    ) -> str:
        """
        Resolves a campus code to a zone id.

        Only used to narrow when a caller supplies a campus code.
        The twin otherwise reports every zone, because a twin
        that silently hides half the campus is worse than one
        that is slightly wide.
        """

        try:
            result = (
                self._db()
                .table("floors")
                .select("id")
                .eq("building_id", self._building_id(campus_code))
                .limit(1)
                .execute()
            )
        except Exception:
            return ""

        rows = result.data or []

        return rows[0]["id"] if rows else ""

    def _building_id(self, campus_code: str) -> str:
        try:
            result = (
                self._db()
                .table("buildings")
                .select("id")
                .eq("campus_id", self._campus_id(campus_code))
                .limit(1)
                .execute()
            )
        except Exception:
            return ""

        rows = result.data or []

        return rows[0]["id"] if rows else ""

    def _campus_id(self, campus_code: str) -> str:
        try:
            result = (
                self._db()
                .table("campuses")
                .select("id")
                .eq("code", campus_code)
                .limit(1)
                .execute()
            )
        except Exception:
            return ""

        rows = result.data or []

        return rows[0]["id"] if rows else ""

    # ------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------

    def latest_by_metric(
        self, zone_ids: List[str]
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        The most recent reading of every metric, per zone.

        Shaped {zone_id: {metric: row}}.

        One query for the whole campus rather than two per zone:
        a campus of thirty zones would otherwise be sixty round
        trips inside a single page load.

        Keyed on `zone_id`, a UUID foreign key. The code lives on
        `zones`; filtering telemetry by `zone_code` is rejected by
        PostgREST as an unknown column and reads as "no data".
        """

        if not zone_ids:
            return {}

        try:
            result = (
                self._db()
                .table(TELEMETRY)
                .select("zone_id,metric,value,unit,timestamp")
                .in_("zone_id", zone_ids)
                .order("timestamp", desc=True)
                .limit(len(zone_ids) * 40)
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read telemetry for the twin"
            )

            return {}

        newest: Dict[str, Dict[str, Dict[str, Any]]] = {}

        for row in result.data or []:
            zone = str(row.get("zone_id"))
            metric = row.get("metric")

            if not metric:
                continue

            bucket = newest.setdefault(zone, {})

            # Results are newest-first, so the first sighting of
            # a metric is the most recent one. Later duplicates
            # for the same metric are older and are skipped.
            if metric not in bucket:
                bucket[metric] = {
                    "value": _num(row.get("value")),
                    "unit": row.get("unit"),
                    "timestamp": row.get("timestamp"),
                }

        return newest

    # ------------------------------------------------------
    # Issues
    # ------------------------------------------------------

    def open_incidents(
        self, zone_ids: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Incidents that are still open, grouped by zone.

        Only statuses that mean "someone still needs to deal with
        it". A resolved incident is history, not a reason to paint
        a marker.
        """

        if not zone_ids:
            return {}

        try:
            result = (
                self._db()
                .table(INCIDENTS)
                .select(
                    "zone_id,title,severity,status,category,"
                    "created_at"
                )
                .in_("zone_id", zone_ids)
                .in_(
                    "status",
                    ["open", "acknowledged", "investigating"],
                )
                .order("created_at", desc=True)
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read incidents for the twin"
            )

            return {}

        grouped: Dict[str, List[Dict[str, Any]]] = {}

        for row in result.data or []:
            grouped.setdefault(
                str(row.get("zone_id")), []
            ).append(row)

        return grouped

    def latest_correlation(
        self, zone_code: str
    ) -> Optional[Dict[str, Any]]:
        """The newest correlation run for a zone."""

        try:
            result = (
                self._db()
                .table(CORRELATION_RUNS)
                .select(
                    "id,result_status,root_cause,evidence_score"
                )
                .eq("zone_code", zone_code)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read the correlation run for '%s'",
                zone_code,
            )

            return None

        rows = result.data or []

        return rows[0] if rows else None

    def pending_approval_count(
        self, zone_ids: List[str]
    ) -> Dict[str, int]:
        """
        How many approvals are waiting, by zone.

        Joined through the simulation rather than stored on the
        approval, so an approval cannot claim to be for a zone it
        is not.
        """

        if not zone_ids:
            return {}

        try:
            runs = (
                self._db()
                .table("simulation_runs")
                .select("id")
                .execute()
            )
        except Exception:
            return {}

        run_ids = [
            row["id"] for row in (runs.data or []) if row.get("id")
        ]

        if not run_ids:
            return {}

        try:
            pending = (
                self._db()
                .table(APPROVALS)
                .select("simulation_id")
                .in_("simulation_id", run_ids)
                .eq("status", "pending")
                .execute()
            )
        except Exception:
            return {}

        wanted = {str(i) for i in run_ids}

        counts = {zone: 0 for zone in zone_ids}

        # Map run -> zone through the zone code each simulation
        # was run against. `zone_ids` is a list of UUIDs, not
        # zone records, so the code lookup needs its own map
        # built from the zones table rather than from that list.
        try:
            zone_rows = (
                self._db()
                .table(ZONES)
                .select("id,code")
                .in_("id", list(zone_ids))
                .execute()
            )
        except Exception:
            return counts

        id_for_code = {
            str(row.get("code")): str(row.get("id"))
            for row in (zone_rows.data or [])
        }

        try:
            sims = (
                self._db()
                .table("simulation_runs")
                .select("id,zone_code")
                .in_("id", list(wanted))
                .execute()
            )
        except Exception:
            return counts

        zone_for_run = {
            str(row.get("id")): str(row.get("zone_code"))
            for row in (sims.data or [])
        }

        for row in pending.data or []:
            code = zone_for_run.get(
                str(row.get("simulation_id"))
            )

            zone_id = id_for_code.get(code or "")

            if zone_id:
                counts[zone_id] = counts.get(zone_id, 0) + 1

        return counts