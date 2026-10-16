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

# Sensors in one tick share a timestamp, so a flush batch asks
# the same context questions five times over. Memoising on that
# shared key keeps one query per tick instead of one per sensor.
CONTEXT_CACHE_SIZE = 256

# Context reads are retried on a transient failure: telemetry is
# already committed by then, so a dropped connection would
# silently cost an incident that cannot be recovered later.
CONTEXT_RETRY_ATTEMPTS = 3
CONTEXT_RETRY_BACKOFF_SECONDS = 0.2

OPEN_STATUSES = ("open", "acknowledged", "investigating")


# Bands used by `compare_occupancy_sources`. Defined here
# rather than imported from `vision.config` so the correlation
# logic stays usable when the vision feature is switched off
# entirely: comparing a camera count against a sensor count is
# meaningful from recorded observations alone, and must not
# depend on OpenCV or a model being present.
CONSISTENCY_TOLERANCE = 5

SIGNIFICANT_DISCREPANCY_THRESHOLD = 10


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
        self._read_cache: Dict[tuple, List[Dict[str, Any]]] = {}
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

        # Context must describe the moment of the reading, not
        # the moment the batch happened to be flushed.
        observed_at = self._as_datetime(
            row.get("timestamp")
        )

        rule_context = self._rule_context(
            zone_id, metric, observed_at
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
            timestamp=observed_at,
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
        Evaluates a reading identified by sensor.

        The spec-facing entry point: it exists so a caller can
        ask "would this reading raise an incident?" without
        holding a full telemetry row.

        It deliberately does not reimplement anything. The sensor
        is resolved, the reading is shaped into a row, and
        `process_reading` does the rest. Two independent paths
        through the rules would inevitably drift apart.
        """

        sensor = self._sensor(sensor_id)

        if sensor is None:
            raise ValueError(
                f"Sensor not found: {sensor_id}"
            )

        zone_id = sensor.get("zone_id")

        if zone_id is None:
            return None

        return self.process_reading(
            {
                "zone_id": zone_id,
                "sensor_id": sensor["id"],
                "metric": metric,
                "value": float(value),
                "timestamp": (
                    timestamp.isoformat()
                    if isinstance(timestamp, datetime)
                    else timestamp
                ),
            }
        )

    # --- rule context --------------------------------------------

    def _rule_context(
        self,
        zone_id: str,
        metric: str,
        observed_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        The keyword arguments the rules for `metric` accept.

        Occupancy is included for every rule because comfort and
        air-quality rules must not fire in an empty zone. The
        energy baseline is only fetched for the energy rule,
        which is the only one that needs it.
        """

        context: Dict[str, Any] = {
            "occupancy": self._occupancy_at(
                zone_id, observed_at
            ),
            "capacity": self._capacity(zone_id),
        }

        if metric == "energy":
            context["baseline_kw"] = self._energy_baseline(
                zone_id, observed_at
            )

        return context

    def _capacity(
        self,
        zone_id: str,
    ) -> Optional[int]:
        context = self._contexts.get(zone_id)

        return context.capacity if context else None

    def _occupancy_at(
        self,
        zone_id: str,
        at: Optional[datetime],
    ) -> Optional[float]:
        """
        Occupancy as it stood when the reading was taken.

        Read "as of" the reading rather than as the newest value,
        because evaluation runs after the write. Quoting the
        newest occupancy would attach evidence from a moment the
        reading never saw: a CO2 spike recorded during a full
        hall could be filed against an empty hall, which points a
        reviewer at a faulty sensor instead of at ventilation.
        """

        rows = self._recent_readings(
            zone_id,
            "occupancy",
            limit=1,
            at=at,
            cache_key=("occupancy", zone_id, at),
        )

        if not rows:
            return None

        return float(rows[0]["value"])

    def _energy_baseline(
        self,
        zone_id: str,
        at: Optional[datetime] = None,
    ) -> Optional[float]:
        """
        Approximates a zone's normal draw.

        Uses a low percentile rather than the mean or median so a
        sustained fault does not drag the baseline up and quietly
        stop the rule from firing. A high percentile would be
        worse still: the baseline would track the fault exactly.

        The window is bounded to readings at or before the
        reading being judged, for the same reason occupancy is:
        the baseline must describe the zone as it was.
        """

        rows = self._recent_readings(
            zone_id,
            "energy",
            limit=BASELINE_SAMPLE_SIZE,
            at=at,
            cache_key=("energy", zone_id, at),
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
        at: Optional[datetime] = None,
        cache_key: Optional[tuple] = None,
    ) -> List[Dict[str, Any]]:
        """
        Reads a metric for a zone, newest first.

        `at` bounds the query to readings taken at or before that
        instant. Evaluation happens after the write, so by then
        the zone may have moved on; without the bound the
        evidence attached to an incident describes a moment that
        is not the moment the reading came from.

        Sensors in one tick share a timestamp, so every reading in
        a flush batch asks the identical question. The result is
        memoised on that shared key, which turns five queries per
        batch into one and keeps a burst of traffic from opening
        a connection per sensor. The cache is an optimisation
        only: a cold or evicted cache costs one extra query and
        never changes an answer.
        """

        if cache_key is not None:
            cached = self._read_cache.get(cache_key)

            if cached is not None:
                return cached

        query = (
            get_supabase()
            .table("telemetry_readings")
            .select("value,timestamp")
            .eq("zone_id", zone_id)
            .eq("metric", metric)
        )

        if at is not None:
            query = query.lte("timestamp", at.isoformat())

        rows = self._read_with_retry(
            lambda: query.order(
                "timestamp",
                desc=True,
            )
            .limit(limit)
            .execute()
        )

        if cache_key is not None:
            with self._lock:
                if len(self._read_cache) >= CONTEXT_CACHE_SIZE:
                    self._read_cache.clear()

                self._read_cache[cache_key] = rows

        return rows

    @staticmethod
    def _read_with_retry(call):
        """
        Retries a context read on a transient failure.

        Telemetry is already committed by the time the engine
        runs, so a dropped connection would silently cost an
        incident that can never be recovered afterwards. Context
        reads are cheap, so retrying is the right trade.
        """

        last_error: Optional[Exception] = None

        for attempt in range(CONTEXT_RETRY_ATTEMPTS):
            try:
                result = call()

                return result.data or []

            except Exception as exc:
                last_error = exc

                if attempt + 1 < CONTEXT_RETRY_ATTEMPTS:
                    time.sleep(
                        CONTEXT_RETRY_BACKOFF_SECONDS
                        * (attempt + 1)
                    )

        raise last_error  # type: ignore[misc]

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

    @staticmethod
    def _observation(
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Projects an evidence record down to one observation.

        Applied to stored history as well as to new evidence. A
        record written before this function existed holds whole
        evidence objects inside its own `observations` list, so
        projecting is what flattens those rather than copying
        them forward.
        """

        return {
            "observed_at": record.get("observed_at"),
            "value": record.get("value"),
            "metric": record.get("metric"),
            "impact_score": record.get("impact_score"),
        }

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

        # Take the *observations list*, not the whole record. The
        # record that was stored here previously nested the entire
        # previous evidence inside its own `observations` entry, so
        # the jsonb went one level deeper on every refresh with no
        # bound at all. Past a certain depth the client could no
        # longer parse its own stored row and returned it as raw
        # text, which cost both the campus twin endpoint and
        # de-duplication itself - see app/db/supabase.py for the
        # read side of that.
        record = (existing.get("evidence") or [{}])[0]

        history = [
            self._observation(entry)
            for entry in record.get("observations") or []
        ]

        # A first refresh has no list yet, so the observation that
        # created the incident is carried over rather than dropped.
        if (
            not history
            and record.get("observed_at") is not None
        ):
            history.append(self._observation(record))

        history.append(self._observation(evidence))

        # Bounded so a long-lived incident cannot grow without
        # limit.
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

    # --- multi-source correlation --------------------------------

    def compare_occupancy_sources(
        self,
        iot_occupancy: float,
        vision_occupancy: float,
    ) -> dict:
        """
        Compares a camera count against a sensor count for the
        same zone.

        The two are not interchangeable and neither is presumed
        correct. An occupancy sensor reports a body heat
        signature, so it counts a sleeping person and misses an
        empty chair; a camera counts a visible person and misses
        one behind a pillar. Persistent disagreement therefore
        means a sensor has drifted, the camera view is
        obstructed, or the zone is genuinely changing faster
        than either source can follow.

        Naming which reading disagrees, by how much, and with
        what confidence is what makes that diagnosable. A bare
        "they differ" would leave the reader to work out which
        one to trust.

        Returns a verdict dict. It reports rather than raises:
        a disagreement is a finding, not a failure, and the
        caller decides what to do about it.
        """

        iot = float(iot_occupancy)
        vision = float(vision_occupancy)

        difference = vision - iot
        absolute = abs(difference)

        if absolute < CONSISTENCY_TOLERANCE:
            verdict = "consistent"
        elif absolute < SIGNIFICANT_DISCREPANCY_THRESHOLD:
            verdict = "minor_discrepancy"
        else:
            verdict = "significant_discrepancy"

        # Agreement is scored relative to the larger of the two
        # readings, so "they differ by 4" means the same thing
        # whether the room holds 10 people or 200. Scaling by
        # the larger value rather than a fixed divisor keeps the
        # score meaningful as the building fills up.
        scale = max(vision, iot, 1.0)

        agreement = max(0.0, min(1.0, 1.0 - (absolute / scale)))

        # Which source is higher is stated explicitly. A vision
        # count above the sensor suggests under-reporting by the
        # sensor; below suggests the camera is missing people.
        # The two have different causes, so the direction is
        # the actionable part.
        if verdict == "consistent":
            higher = None
        elif vision > iot:
            higher = "vision"
        else:
            higher = "iot"

        logger.info(
            "Occupancy comparison for zone: iot=%.1f vision=%.1f "
            "difference=%+.1f verdict=%s",
            iot,
            vision,
            difference,
            verdict,
        )

        return {
            "verdict": verdict,
            "iot_occupancy": iot,
            "vision_occupancy": vision,
            "difference": round(difference, 2),
            "absolute_difference": round(absolute, 2),
            "agreement": round(agreement, 4),
            "higher_source": higher,
            "consistent": verdict == "consistent",
        }

    # --- queries -------------------------------------------------

    def list_incidents(
        self,
        campus_code: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        zone_code: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = (
            get_supabase()
            .table("incidents")
            .select("*")
        )

        campus_id: Optional[str] = None

        if campus_code:
            campus_id = self._campus_id(campus_code)

            if campus_id is None:
                return []

            query = query.eq("campus_id", campus_id)

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

        if zone_code:
            zone_ids = self._zone_ids_for_code(
                campus_id, zone_code
            )

            # An unknown zone matches nothing rather than
            # everything.
            if not zone_ids:
                return []

            query = query.in_("zone_id", zone_ids)

        rows = (
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

        # An id is not a label. Callers render these rows for a
        # person, so each row is given the zone code it belongs
        # to.
        self._zone_codes(rows)

        return rows

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

    def _zone_ids_for_code(
        self,
        campus_id: Optional[str],
        zone_code: str,
    ) -> List[str]:
        """
        Resolves a zone code to ids, scoped to a campus when one
        is given.

        Zones carry no campus_id of their own: the chain is
        building to floor to zone. It is walked explicitly rather
        than through a PostgREST embed so this does not depend on
        relationship naming in the database.

        An unknown code resolves to an empty list, which the
        caller turns into "no incidents" rather than "no
        filtering", so a typo narrows the result instead of
        quietly widening it.
        """

        client = get_supabase()

        query = client.table("zones").select("id").eq(
            "code", zone_code
        )

        if campus_id is None:
            # No campus was asked for, so every zone with this
            # code is in scope.
            return [
                item["id"]
                for item in query.execute().data or []
            ]

        buildings = (
            client.table("buildings")
            .select("id")
            .eq("campus_id", campus_id)
            .execute()
            .data
            or []
        )

        if not buildings:
            return []

        floors = (
            client.table("floors")
            .select("id")
            .in_(
                "building_id",
                [item["id"] for item in buildings],
            )
            .execute()
            .data
            or []
        )

        if not floors:
            return []

        zones = (
            query.in_(
                "floor_id",
                [item["id"] for item in floors],
            )
            .execute()
            .data
            or []
        )

        return [item["id"] for item in zones]

    @staticmethod
    def _zone_codes(
        rows: List[Dict[str, Any]],
    ) -> None:
        """
        Adds `zone_code` to each row, in place.

        An incident stores only a zone id, which is not something
        a person recognises. The lookup is one query for the whole
        page rather than one per incident.
        """

        zone_ids = {
            row.get("zone_id")
            for row in rows
            if row.get("zone_id")
        }

        if not zone_ids:
            for row in rows:
                row.setdefault("zone_code", None)

            return

        zones = (
            get_supabase()
            .table("zones")
            .select("id,code")
            .in_("id", list(zone_ids))
            .execute()
            .data
            or []
        )

        codes = {
            item["id"]: item.get("code")
            for item in zones
        }

        for row in rows:
            row["zone_code"] = codes.get(row.get("zone_id"))


# Process-wide instance. The caches on it are process-local and
# are only an optimisation: losing them costs a few database
# reads, never correctness.
intelligence_service = IntelligenceService()
