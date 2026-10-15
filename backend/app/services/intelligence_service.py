"""
Campus intelligence service.

Consumes persisted telemetry, resolves the context a reading
needs to be interpreted (which zone, how full, what the zone
normally draws), runs the deterministic rules, and persists an
incident when one fires.

Two behaviours matter more than the rules themselves:

* **Deduplication.** Telemetry arrives every few seconds. A
  condition that persists for an hour would otherwise produce
  hundreds of identical incidents. An incident is created once
  and then refreshed while it stays open.

* **Non-blocking.** Every method here is synchronous and touches
  the database. Callers run it through `asyncio.to_thread`, which
  also gives it the thread-local Supabase client that the rest of
  the telemetry stack uses.

No schema change is required. The fingerprint used for
deduplication is derived from `zone_id`, `category` and the rule
name already stored inside `evidence`.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import (
    dataclass,
    field,
)
from datetime import datetime, timezone
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
)

from app.core.intelligence_rules import (
    RuleResult,
    evaluate_metric,
)
from app.db.supabase import get_supabase
from app.schemas.intelligence import IntelligenceSummary


logger = logging.getLogger(__name__)


# Two incidents for the same zone and rule inside this window are
# treated as the same finding. Long enough to survive a normal
# jitter gap, short enough that a genuine second event later in
# the day is still reported.
DEDUP_WINDOW_SECONDS = 300

# Cached context is refreshed at most this often. Zone geometry
# changes in minutes; resolving it on every reading would mean a
# database round trip per row.
CONTEXT_TTL_SECONDS = 60

# How many recent readings to consider when estimating a zone's
# normal energy draw.
BASELINE_SAMPLE_SIZE = 200

# Fewer samples than this and there is no baseline to compare
# against, so the energy rule declines rather than guessing.
BASELINE_MIN_SAMPLES = 3

OPEN_STATUSES = ("open", "acknowledged", "investigating")


@dataclass
class ZoneContext:
    """
    Everything a rule needs to interpret a reading, resolved once
    per zone.
    """

    zone_id: str
    zone_code: str
    campus_id: str
    building_id: Optional[str] = None
    floor_id: Optional[str] = None
    capacity: Optional[int] = None
    resolved_at: float = field(default_factory=time.monotonic)


class IntelligenceService:
    """
    Evaluates persisted telemetry and persists incidents.
    """

    def __init__(
        self,
        dedup_window_seconds: int = DEDUP_WINDOW_SECONDS,
        context_ttl_seconds: int = CONTEXT_TTL_SECONDS,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._dedup_window = dedup_window_seconds
        self._context_ttl = context_ttl_seconds
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._contexts: Dict[str, ZoneContext] = {}
        self._lock = threading.Lock()

        self.evaluated = 0
        self.fired = 0
        self.created = 0
        self.refreshed = 0
        self.deduplicated = 0
        self.errors = 0

    # --- statistics ----------------------------------------------

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "evaluated": self.evaluated,
            "fired": self.fired,
            "created": self.created,
            "refreshed": self.refreshed,
            "deduplicated": self.deduplicated,
            "errors": self.errors,
        }

    # --- entry point ---------------------------------------------

    def process_batch(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Evaluates a batch of persisted telemetry rows.

        Called after the rows are written, so an incident always
        references a reading that actually exists. A failure here
        must not lose the telemetry, so per-row errors are
        logged and counted rather than raised.
        """

        incidents: List[Dict[str, Any]] = []

        for row in rows:
            try:
                incident = self.process_reading(row)

                if incident is not None:
                    incidents.append(incident)

            except Exception:
                self.errors += 1

                logger.exception(
                    "Intelligence evaluation failed for "
                    "metric=%s sensor=%s",
                    row.get("metric"),
                    row.get("sensor_id"),
                )

        return incidents

    def process_reading(
        self,
        row: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates one persisted reading and persists an incident
        when a rule fires.
        """

        metric = row.get("metric")
        value = row.get("value")

        if metric is None or value is None:
            return None

        self.evaluated += 1

        zone_id = row.get("zone_id")

        if zone_id is None:
            # Nothing to attribute an incident to without a zone.
            return None

        context = self._zone_context(zone_id)

        if context is None:
            return None

        rule_context = self._rule_context(
            zone_id, metric
        )

        result = evaluate_metric(
            metric, float(value), rule_context
        )

        if result is None:
            return None

        self.fired += 1

        return self._persist(
            result=result,
            context=context,
            sensor_id=row.get("sensor_id"),
            timestamp=self._as_datetime(
                row.get("timestamp")
            ),
            metric=metric,
            value=float(value),
        )

    @staticmethod
    def _as_datetime(
        value: Any,
    ) -> Optional[datetime]:
        """
        Normalises a stored timestamp back into a datetime.
        """

        if isinstance(value, datetime):
            return value

        if value is None:
            return None

        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed

    def create_incident(
        self,
        sensor_id: str,
        metric: str,
        value: float,
        timestamp: datetime,
    ) -> Optional[Dict[str, Any]]:
        """
        Spec-facing entry point: evaluate a reading identified by
        sensor, without needing a full telemetry row.
        """

        sensor = self._sensor(sensor_id)

        if sensor is None:
            raise ValueError(
                f"Sensor not found: {sensor_id}"
            )

        zone_id = sensor.get("zone_id")

        if zone_id is None:
            return None

        context = self._zone_context(zone_id)

        if context is None:
            return None

        result = evaluate_metric(
            metric,
            float(value),
            self._rule_context(zone_id, metric),
        )

        if result is None:
            return None

        self.fired += 1

        return self._persist(
            result=result,
            context=context,
            sensor_id=sensor_id,
            timestamp=timestamp,
            metric=metric,
            value=value,
        )

    # --- rule context --------------------------------------------

    def _rule_context(
        self,
        zone_id: str,
        metric: str,
    ) -> Dict[str, Any]:
        """
        The keyword arguments the rules for `metric` accept.

        Occupancy is included for every rule because comfort and
        air-quality rules must not fire in an empty zone. The
        energy baseline is only fetched for the energy rule,
        which is the only one that needs it.
        """

        context: Dict[str, Any] = {
            "occupancy": self._latest_occupancy(zone_id),
            "capacity": self._capacity(zone_id),
        }

        if metric == "energy":
            context["baseline_kw"] = self._energy_baseline(
                zone_id
            )

        return context

    def _capacity(
        self,
        zone_id: str,
    ) -> Optional[int]:
        context = self._contexts.get(zone_id)

        return context.capacity if context else None

    def _latest_occupancy(
        self,
        zone_id: str,
    ) -> Optional[float]:
        rows = self._recent_readings(
            zone_id, "occupancy", limit=1
        )

        if not rows:
            return None

        return float(rows[0]["value"])

    def _energy_baseline(
        self,
        zone_id: str,
    ) -> Optional[float]:
        """
        Approximates a zone's normal draw.

        Uses a low percentile rather than the mean or median so a
        sustained fault does not drag the baseline up and quietly
        stop the rule from firing. A high percentile would be
        worse still: the baseline would track the fault exactly.
        """

        rows = self._recent_readings(
            zone_id, "energy", limit=BASELINE_SAMPLE_SIZE
        )

        values = sorted(
            float(row["value"]) for row in rows
        )

        if len(values) < BASELINE_MIN_SAMPLES:
            return None

        index = int(len(values) * 0.2)

        return values[min(index, len(values) - 1)]

    def _recent_readings(
        self,
        zone_id: str,
        metric: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        result = (
            get_supabase()
            .table("telemetry_readings")
            .select("value,timestamp")
            .eq("zone_id", zone_id)
            .eq("metric", metric)
            .order(
                "timestamp",
                desc=True,
            )
            .limit(limit)
            .execute()
        )

        return result.data or []

    # --- zone context --------------------------------------------

    def _zone_context(
        self,
        zone_id: str,
    ) -> Optional[ZoneContext]:
        """
        Resolves a zone and everything above it.

        Campus is three hops away: zones have no campus_id, they
        hang off a floor, which hangs off a building. The hops are
        resolved separately rather than through a PostgREST embed
        so this does not depend on relationship naming in the
        database.
        """

        now = time.monotonic()

        with self._lock:
            cached = self._contexts.get(zone_id)

            if (
                cached is not None
                and now - cached.resolved_at < self._context_ttl
            ):
                return cached

        client = get_supabase()

        zone = (
            client.table("zones")
            .select("id,code,capacity,floor_id")
            .eq("id", zone_id)
            .limit(1)
            .execute()
            .data
        )

        if not zone:
            return None

        zone_row = zone[0]
        floor_id = zone_row.get("floor_id")

        building_id = None
        campus_id = None

        if floor_id:
            floor = (
                client.table("floors")
                .select("id,building_id")
                .eq("id", floor_id)
                .limit(1)
                .execute()
                .data
            )

            if not floor:
                return None

            building_id = floor[0].get("building_id")

        if building_id:
            building = (
                client.table("buildings")
                .select("id,campus_id")
                .eq("id", building_id)
                .limit(1)
                .execute()
                .data
            )

            if not building:
                return None

            campus_id = building[0].get("campus_id")

        if campus_id is None:
            # Without a campus an incident cannot be attributed.
            return None

        context = ZoneContext(
            zone_id=zone_row["id"],
            zone_code=zone_row["code"],
            campus_id=campus_id,
            building_id=building_id,
            floor_id=floor_id,
            capacity=zone_row.get("capacity"),
            resolved_at=now,
        )

        with self._lock:
            self._contexts[zone_id] = context

        return context

    def _sensor(
        self,
        sensor_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolves a sensor by UUID, falling back to code, because
        the Phase 5 topic hierarchy uses UUIDs while operators
        refer to sensors by code.
        """

        rows = (
            get_supabase()
            .table("sensors")
            .select("id,code,zone_id,equipment_id")
            .eq("id", sensor_id)
            .limit(1)
            .execute()
            .data
        )

        if rows:
            return rows[0]

        return (
            get_supabase()
            .table("sensors")
            .select("id,code,zone_id,equipment_id")
            .eq("code", sensor_id)
            .limit(1)
            .execute()
            .data
            or [None]
        )[0]

    # --- persistence ---------------------------------------------

    def _persist(
        self,
        result: RuleResult,
        context: ZoneContext,
        sensor_id: Optional[str],
        timestamp: Optional[datetime] = None,
        metric: Optional[str] = None,
        value: Optional[float] = None,
    ) -> Dict[str, Any]:
        rule_name = str(
            (result.evidence or [{}])[0].get(
                "rule", "unknown"
            )
        )

        evidence = self._build_evidence(
            result=result,
            context=context,
            sensor_id=sensor_id,
            metric=metric,
            value=value,
            timestamp=timestamp,
        )

        detected_at = timestamp or self._clock()

        existing = self._find_open_incident(
            context.zone_id,
            result.category,
            rule_name,
        )

        if existing is not None:
            return self._refresh_incident(
                existing, evidence
            )

        row = {
            "campus_id": context.campus_id,
            "building_id": context.building_id,
            "zone_id": context.zone_id,
            "sensor_id": sensor_id,
            "equipment_id": None,
            "category": result.category,
            "severity": result.severity,
            "status": "open",
            "title": result.title,
            "description": result.description,
            "impact_score": float(result.impact_score),
            "confidence_score": float(
                result.confidence_score
            ),
            "detection_method": "deterministic_rule",
            "evidence": [evidence],
            "detected_at": detected_at.isoformat(),
        }

        inserted = (
            get_supabase()
            .table("incidents")
            .insert(row)
            .execute()
            .data
        )

        if not inserted:
            self.errors += 1
            return {}

        self.created += 1

        logger.info(
            "Incident created: %s [%s/%s] impact=%.1f "
            "rule=%s",
            result.title,
            result.category,
            result.severity,
            result.impact_score,
            rule_name,
        )

        return inserted[0]

    def _build_evidence(
        self,
        result: RuleResult,
        context: ZoneContext,
        sensor_id: Optional[str],
        metric: Optional[str],
        value: Optional[float],
        timestamp: Optional[datetime],
    ) -> Dict[str, Any]:
        """
        Flattens the rule's own measurements together with the
        observation that triggered it, so one evidence object
        answers: what rule, what sensor, what zone, what value,
        when, and what else was true at the time.
        """

        evidence: Dict[str, Any] = {}

        for item in result.evidence or []:
            evidence.update(item)

        evidence["zone"] = context.zone_code
        evidence["zone_id"] = context.zone_id

        if context.building_id:
            evidence["building_id"] = context.building_id

        if context.capacity:
            evidence["capacity"] = context.capacity

        if sensor_id:
            evidence["sensor_id"] = sensor_id

        if metric is not None:
            evidence["metric"] = metric

        if value is not None:
            evidence["value"] = round(float(value), 4)

        evidence["confidence_score"] = float(
            result.confidence_score
        )
        evidence["impact_score"] = float(result.impact_score)
        evidence["observed_at"] = (
            timestamp or self._clock()
        ).isoformat()

        return evidence

    def _find_open_incident(
        self,
        zone_id: str,
        category: str,
        rule_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Finds a recent open incident for the same zone, category
        and rule.

        Derived from existing columns rather than a stored
        fingerprint, because Phase 6 does not change the schema.
        """

        cutoff = self._clock().timestamp() - (
            self._dedup_window
        )

        rows = (
            get_supabase()
            .table("incidents")
            .select(
                "id,title,severity,impact_score,evidence,"
                "detected_at"
            )
            .eq("zone_id", zone_id)
            .eq("category", category)
            .in_("status", list(OPEN_STATUSES))
            .order(
                "detected_at",
                desc=True,
            )
            .limit(20)
            .execute()
            .data
            or []
        )

        for row in rows:
            detected = row.get("detected_at")

            if detected is None:
                continue

            if self._to_epoch(detected) < cutoff:
                continue

            for item in row.get("evidence") or []:
                if item.get("rule") == rule_name:
                    return row

        return None

    @staticmethod
    def _to_epoch(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)

        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError:
            return 0.0

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.timestamp()

    def _refresh_incident(
        self,
        existing: Dict[str, Any],
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Records a new observation against an already-open
        incident.

        The latest evidence replaces the stored one so a reviewer
        sees the most recent measurements, and the impact score
        tracks the worst value seen rather than the first.
        """

        history = list(existing.get("evidence") or [])

        history.append(
            {
                "observed_at": evidence.get(
                    "observed_at"
                ),
                "value": evidence.get("value"),
                "metric": evidence.get("metric"),
                "impact_score": evidence.get(
                    "impact_score"
                ),
            }
        )

        # Keep a bounded history so a long-lived incident cannot
        # grow without limit.
        merged = evidence.copy()
        merged["observations"] = history[-50:]

        prior_impact = float(
            existing.get("impact_score") or 0.0
        )

        impact = max(
            prior_impact,
            float(evidence.get("impact_score") or 0.0),
        )

        updated = (
            get_supabase()
            .table("incidents")
            .update(
                {
                    "evidence": [merged],
                    "impact_score": impact,
                }
            )
            .eq("id", existing["id"])
            .execute()
            .data
        )

        if not updated:
            self.errors += 1
            return {}

        self.refreshed += 1
        self.deduplicated += 1

        logger.debug(
            "Incident %s refreshed (deduplicated)",
            existing["id"],
        )

        return updated[0]

    # --- queries -------------------------------------------------

    def list_incidents(
        self,
        campus_code: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = (
            get_supabase()
            .table("incidents")
            .select("*")
        )

        if status:
            query = query.in_(
                "status", [status]
            )

        if severity:
            query = query.in_(
                "severity", [severity]
            )

        if category:
            query = query.in_(
                "category", [category]
            )

        if campus_code:
            campus = self._campus_id(campus_code)

            if campus is None:
                return []

            query = query.eq("campus_id", campus)

        return (
            query.order(
                "impact_score", desc=True
            )
            .order(
                "detected_at", desc=True
            )
            .limit(limit)
            .execute()
            .data
            or []
        )

    def summary(
        self,
        campus_code: str,
    ) -> IntelligenceSummary:
        campus_id = self._campus_id(campus_code)

        if campus_id is None:
            return IntelligenceSummary(
                campus_code=campus_code,
                total_incidents=0,
                critical=0,
                high=0,
                medium=0,
                low=0,
                open_incidents=0,
                highest_impact=0.0,
            )

        rows = (
            get_supabase()
            .table("incidents")
            .select("severity,status,impact_score")
            .eq("campus_id", campus_id)
            .execute()
            .data
            or []
        )

        counts = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        }

        open_count = 0
        highest = 0.0

        for row in rows:
            severity = row.get("severity")

            if severity in counts:
                counts[severity] += 1

            if row.get("status") in OPEN_STATUSES:
                open_count += 1

            impact = float(row.get("impact_score") or 0.0)

            highest = max(highest, impact)

        return IntelligenceSummary(
            campus_code=campus_code,
            total_incidents=len(rows),
            critical=counts["critical"],
            high=counts["high"],
            medium=counts["medium"],
            low=counts["low"],
            open_incidents=open_count,
            highest_impact=round(highest, 2),
        )

    def _campus_id(
        self,
        campus_code: str,
    ) -> Optional[str]:
        rows = (
            get_supabase()
            .table("campuses")
            .select("id")
            .eq("code", campus_code)
            .limit(1)
            .execute()
            .data
        )

        return rows[0]["id"] if rows else None

    def stats_snapshot(self) -> Dict[str, Any]:
        return self.stats


# Process-wide instance. The caches on it are process-local and
# are only an optimisation: losing them costs a few database
# reads, never correctness.
intelligence_service = IntelligenceService()
