"""
Correlation service (Phase 8).

This is where independent sources are brought together and
judged as one body of evidence rather than three separate
readings.

The principle the whole module implements: no single signal may
declare a problem on its own. An empty room and a high energy
draw are two facts; whether they add up to waste depends on
evidence that neither of them supplies. Is the camera sure? Is
the count current? Is the energy feed alive, and is it current?
Should the room be occupied at all right now? Only when every
one of those holds does the engine return a candidate, and even
then it says "potential", because a model of a room is not a
measurement of it.

Every analysis is persisted. A conclusion that cannot be
reconstructed afterwards is not evidence, and the correlation
run is what makes the decision auditable.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.correlation_rules import (
    DEFAULT_CORRELATION_CONFIG,
    RESULT_CONFIRMED_CANDIDATE,
    RESULT_NEEDS_REVIEW,
    RESULT_NORMAL,
    CorrelationConfig,
    EvidenceCheck,
    blocking_check,
    calculate_confidence_score,
    calculate_energy_ratio,
    calculate_evidence_score,
    calculate_occupancy_ratio,
    check_energy_anomaly,
    check_energy_evidence,
    check_occupancy_low,
    check_observation_freshness,
    check_schedule_active,
    check_vision_evidence,
    expected_energy_kw,
    occupancy_state,
    parse_timestamp,
)
from app.db.supabase import get_supabase


logger = logging.getLogger(__name__)


# Root causes. Constrained wording, no exceptions: the engine
# reports modelled conditions and must never present one as a
# proven physical fault or a realised saving.
ROOT_CAUSE_ENERGY_WASTE = (
    "Potential energy waste during low occupancy"
)

ROOT_CAUSE_OVER_CAPACITY = (
    "Potential occupancy above zone capacity"
)


# Checks whose failure means "the condition is not present"
# rather than "the evidence is incomplete".
#
# Distinguishing these two is what stops a healthy building from
# filling a review queue. Failing to find an anomaly is a normal
# outcome; being unable to tell is a reason to ask a human.
_NOT_A_CONDITION = frozenset(
    {"energy_anomaly", "occupancy_low"}
)


class CorrelationService:
    """
    Evaluates a zone against vision, telemetry and schedule.
    """

    def __init__(
        self,
        config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
    ):
        self.config = config

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_float(value) -> Optional[float]:
        """
        Coerces a stored value to a float, or None.

        Storage is `numeric`, which PostgREST may return as a
        string, a number or null depending on the driver. Every
        conversion failure is treated as "no value" so a schema
        surprise downgrades the evidence instead of raising
        inside a request.
        """

        if value is None:
            return None

        try:
            result = float(value)
        except (TypeError, ValueError):
            return None

        if result != result:  # NaN
            return None

        return result

    @staticmethod
    def _latest_observation(
        zone_code: str,
    ) -> Optional[Dict[str, Any]]:
        """
        The most recent camera observation for a zone.

        Reads `observations`, which is the Phase 8 model. The
        legacy `vision_observations` table is not consulted: two
        sources of truth for the same fact would let the engine
        judge a zone against a reading that was never stored in
        the place the audit trail expects it.
        """

        try:
            result = (
                get_supabase()
                .table("observations")
                .select(
                    "id,zone_code,source_type,observation_type,"
                    "value,unit,confidence,evidence_status,"
                    "observed_at,created_at"
                )
                .eq("zone_code", zone_code)
                .in_(
                    "observation_type",
                    ["occupancy", "people_count"],
                )
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            # A read failure is missing evidence, so it is
            # reported rather than raised. The gate will
            # downgrade for want of a camera count, which is the
            # correct outcome.
            logger.exception(
                "Failed to read the latest observation for '%s'",
                zone_code,
            )

            return None

        rows = result.data or []

        return rows[0] if rows else None

    @staticmethod
    def _latest_energy(
        zone_code: str,
        zone_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        The most recent energy telemetry row for a zone.

        `telemetry_readings` is keyed on `zone_id`, not
        `zone_code`: it is a UUID foreign key, and the code lives
        on `zones`. Filtering it by `zone_code` would be rejected
        by PostgREST as an unknown column, which reads as "no
        telemetry" and silently downgrades every verdict.
        """

        if zone_id is None:
            return None

        try:
            result = (
                get_supabase()
                .table("telemetry_readings")
                .select("value,timestamp,zone_id")
                .eq("zone_id", zone_id)
                .eq("metric", "energy")
                .order("timestamp", desc=True)
                .limit(1)
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read energy telemetry for '%s'",
                zone_code,
            )

            return None

        rows = result.data or []

        return rows[0] if rows else None

    @staticmethod
    def _energy_baseline(
        zone_code: str,
        zone_id: Optional[str] = None,
    ) -> Optional[float]:
        """
        A measured baseline for a zone, when one exists.

        The median of recent readings rather than the newest, so
        a sustained fault does not become the new normal. A high
        percentile would be worse: the baseline would track the
        fault exactly and the zone would look healthy.
        """

        if zone_id is None:
            return None

        try:
            result = (
                get_supabase()
                .table("telemetry_readings")
                .select("value")
                .eq("zone_id", zone_id)
                .eq("metric", "energy")
                .order("timestamp", desc=True)
                .limit(200)
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read an energy baseline for '%s'",
                zone_code,
            )

            return None

        values = sorted(
            value
            for value in (
                CorrelationService._to_float(
                    row.get("value")
                )
                for row in (result.data or [])
            )
            if value is not None and value >= 0
        )

        # Three samples is the minimum for a median to describe
        # anything. Fewer is not a baseline.
        if len(values) < 3:
            return None

        return values[len(values) // 2]

    @staticmethod
    def _zone(zone_code: str) -> Optional[Dict[str, Any]]:
        """
        The zone row, which carries both the capacity and the
        UUID that `telemetry_readings` is keyed on.
        """

        try:
            result = (
                get_supabase()
                .table("zones")
                .select("id,code,capacity")
                .eq("code", zone_code)
                .limit(1)
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read zone '%s'", zone_code
            )

            return None

        rows = result.data or []

        return rows[0] if rows else None

    # ============================================================
    # PERSISTENCE
    # ============================================================

    def _persist_run(
        self,
        zone_code: str,
        result_status: str,
        root_cause: Optional[str],
        evidence_score: float,
        confidence_score: float,
        findings: List[Dict[str, Any]],
        observation_id: Optional[str] = None,
        telemetry_window: Optional[
            Dict[str, datetime]
        ] = None,
    ) -> Optional[str]:
        """
        Records the analysis.

        A run is written for every outcome, including `normal`.
        The audit trail is most valuable for the analyses that
        did nothing, because those are the ones a reviewer will
        later ask about.
        """

        window = telemetry_window or {}

        payload = {
            "zone_code": zone_code,
            "observation_id": observation_id,
            "telemetry_window_start": (
                window["start"].isoformat()
                if window.get("start")
                else None
            ),
            "telemetry_window_end": (
                window["end"].isoformat()
                if window.get("end")
                else None
            ),
            "result_status": result_status,
            "root_cause": root_cause,
            "evidence_score": evidence_score,
            "confidence_score": confidence_score,
            "findings": findings,
        }

        try:
            stored = (
                get_supabase()
                .table("correlation_runs")
                .insert(payload)
                .execute()
            )
        except Exception:
            # The analysis itself succeeded and is returned; only
            # the audit copy is missing. Failing the request here
            # would discard a conclusion the caller can still
            # act on, so it is logged loudly instead.
            logger.exception(
                "Correlation run for '%s' could not be stored; "
                "the conclusion is still being returned",
                zone_code,
            )

            return None

        rows = getattr(stored, "data", None) or []

        if rows and isinstance(rows[0], dict):
            return rows[0].get("id")

        return None

    # ============================================================
    # CORE EVALUATION
    # ============================================================

    def evaluate_energy_waste(
        self,
        occupancy: Optional[float],
        confidence: Optional[float],
        energy_kw: Optional[float] = None,
        energy_timestamp: Optional[datetime] = None,
        capacity: Optional[int] = None,
        schedule_active: bool = True,
        observation_timestamp: Optional[datetime] = None,
        baseline_kw: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Applies the evidence gate and returns a verdict.

        Pure: it reads nothing and writes nothing, so the whole
        gate is testable without a database. `correlate` gathers
        the evidence and calls this.
        """

        moment = now or self._utc_now()

        # Stored timestamps arrive as ISO strings from PostgREST
        # and as datetimes from tests and callers. Normalising
        # here means every freshness check sees the same type.
        if isinstance(energy_timestamp, str):
            energy_timestamp = parse_timestamp(
                energy_timestamp
            )

        if isinstance(observation_timestamp, str):
            observation_timestamp = parse_timestamp(
                observation_timestamp
            )

        occupancy_ratio = calculate_occupancy_ratio(
            occupancy, capacity
        )

        expected = expected_energy_kw(
            energy_kw, baseline_kw, capacity, self.config
        )

        ratio = calculate_energy_ratio(energy_kw, expected)

        state = occupancy_state(
            occupancy_ratio, self.config
        )

        # Every gate condition, evaluated whether or not it is
        # reached, so the response can show the complete picture
        # rather than stopping at the first failure.
        checks = [
            check_vision_evidence(
                occupancy, confidence, self.config
            ),
            check_observation_freshness(
                observation_timestamp, moment, self.config
            ),
            check_energy_evidence(
                energy_kw,
                energy_timestamp,
                moment,
                self.config,
            ),
            check_schedule_active(schedule_active),
            check_energy_anomaly(ratio, self.config),
            check_occupancy_low(
                occupancy_ratio, self.config
            ),
        ]

        evidence_score = calculate_evidence_score(checks)

        # Over-capacity is a different condition from wasted
        # energy and is reported as such. A room above its
        # capacity is a ventilation and safety concern; calling
        # it energy waste would send whoever reads the alert to
        # the wrong subsystem entirely.
        if (
            state == "over_capacity"
            and checks[0].passed
            and checks[1].passed
            and checks[2].passed
        ):
            result_status = RESULT_CONFIRMED_CANDIDATE
            root_cause = ROOT_CAUSE_OVER_CAPACITY
        else:
            failure = blocking_check(checks)

            # A room that is simply occupied, or drawing a normal
            # amount of power, is not a finding and not a
            # concern. These two checks describe the absence of
            # the condition being looked for, so failing them
            # means there is nothing to explain and nothing to
            # ask a reviewer about. Reporting them as
            # `needs_review` would fill the review queue with
            # healthy rooms and train everyone to ignore it.
            if failure is None:
                result_status = RESULT_CONFIRMED_CANDIDATE
                root_cause = ROOT_CAUSE_ENERGY_WASTE
            elif failure.name in _NOT_A_CONDITION:
                # `occupancy_low` is only "the condition is
                # absent" when the room was actually assessed. If
                # capacity is unknown the ratio is None, the
                # check failed because the evidence was missing
                # rather than because the room was busy, and
                # that is a reason to ask a human.
                if (
                    failure.name == "occupancy_low"
                    and occupancy_ratio is None
                ):
                    result_status = RESULT_NEEDS_REVIEW
                else:
                    result_status = RESULT_NORMAL

                root_cause = None
            else:
                result_status = RESULT_NEEDS_REVIEW
                root_cause = None

        confidence_score = (
            calculate_confidence_score(
                confidence, ratio, self.config
            )
            if result_status == RESULT_CONFIRMED_CANDIDATE
            else 0.0
        )

        return {
            "zone_code": None,
            "result_status": result_status,
            "root_cause": root_cause,
            "evidence_score": evidence_score,
            "confidence_score": confidence_score,
            "occupancy": occupancy,
            "energy_kw": (
                self._to_float(energy_kw)
                if energy_kw is not None
                else None
            ),
            "expected_energy_kw": (
                round(expected, 4)
                if expected is not None
                else None
            ),
            "energy_ratio": (
                round(ratio, 4)
                if ratio is not None
                else None
            ),
            "occupancy_ratio": (
                round(occupancy_ratio, 4)
                if occupancy_ratio is not None
                else None
            ),
            "occupancy_state": state,
            "schedule_active": schedule_active,
            "evidence": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "score": check.score,
                    "reason": check.reason,
                }
                for check in checks
            ],
        }

    def correlate(
        self,
        zone_code: str,
        schedule_active: bool = True,
    ) -> Dict[str, Any]:
        """
        Gathers the evidence for a zone, applies the gate and
        records the result.
        """

        now = self._utc_now()

        observation = self._latest_observation(zone_code)
        zone = self._zone(zone_code)

        capacity = zone.get("capacity") if zone else None
        zone_id = zone.get("id") if zone else None

        energy = self._latest_energy(zone_code, zone_id)
        baseline = self._energy_baseline(zone_code, zone_id)

        occupancy = None
        confidence = None
        observed_at = None
        observation_id = None

        if observation:
            occupancy = self._to_float(
                observation.get("value")
            )
            confidence = self._to_float(
                observation.get("confidence")
            )
            observed_at = parse_timestamp(
                observation.get("observed_at")
            )
            observation_id = observation.get("id")

        energy_kw = None
        energy_at = None

        if energy:
            energy_kw = self._to_float(energy.get("value"))
            energy_at = parse_timestamp(
                energy.get("timestamp")
            )

        verdict = self.evaluate_energy_waste(
            occupancy=occupancy,
            confidence=confidence,
            energy_kw=energy_kw,
            energy_timestamp=energy_at,
            capacity=capacity,
            schedule_active=schedule_active,
            observation_timestamp=observed_at,
            baseline_kw=baseline,
            now=now,
        )

        verdict["zone_code"] = zone_code

        run_id = self._persist_run(
            zone_code=zone_code,
            result_status=verdict["result_status"],
            root_cause=verdict["root_cause"],
            evidence_score=verdict["evidence_score"],
            confidence_score=verdict["confidence_score"],
            findings=verdict["evidence"],
            observation_id=observation_id,
            telemetry_window={
                "start": energy_at,
                "end": energy_at,
            }
            if energy_at
            else None,
        )

        verdict["correlation_run_id"] = run_id

        logger.info(
            "Correlation for '%s': %s (evidence %.0f, confidence "
            "%.0f)",
            zone_code,
            verdict["result_status"],
            verdict["evidence_score"],
            verdict["confidence_score"],
        )

        return verdict

    # ============================================================
    # QUERIES
    # ============================================================

    def recent_runs(
        self,
        zone_code: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """The recorded analyses for a zone, newest first."""

        try:
            result = (
                get_supabase()
                .table("correlation_runs")
                .select(
                    "id,zone_code,result_status,root_cause,"
                    "evidence_score,confidence_score,findings,"
                    "created_at"
                )
                .eq("zone_code", zone_code)
                .order("created_at", desc=True)
                .limit(max(1, min(limit, 100)))
                .execute()
            )
        except Exception:
            logger.exception(
                "Failed to read correlation runs for '%s'",
                zone_code,
            )

            return []

        return result.data or []


correlation_service = CorrelationService()