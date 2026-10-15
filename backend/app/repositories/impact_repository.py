"""
Impact and correlation repository.

Phase 9 and 10 reason from a *stored* correlation run rather
than re-running the evidence gate. That is deliberate: a
decision attached to evidence nobody recorded cannot be audited,
and a fresh judgement might differ from the one that justified
the finding in the first place.
"""

import logging
from typing import Any, Dict, List, Optional

from app.db.supabase import get_supabase


logger = logging.getLogger(__name__)


CORRELATION_RUNS = "correlation_runs"
OBSERVATIONS = "observations"
TELEMETRY = "telemetry_readings"
ZONES = "zones"


def latest_correlation_run(
    zone_code: str,
    status: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    The most recent correlation run for a zone.

    Defaults to the most recent run of any status. A caller that
    needs a confirmed finding asks for one explicitly rather
    than having it imposed, because a run whose verdict was
    `normal` is still the best available evidence about the
    zone and should be visible in the audit trail.
    """

    try:
        query = (
            get_supabase()
            .table(CORRELATION_RUNS)
            .select(
                "id,zone_code,result_status,root_cause,"
                "evidence_score,confidence_score,findings,"
                "created_at"
            )
            .eq("zone_code", zone_code)
        )

        if status:
            query = query.eq("result_status", status)

        result = (
            query.order("created_at", desc=True).limit(1).execute()
        )
    except Exception:
        logger.exception(
            "Failed to read the latest correlation run for '%s'",
            zone_code,
        )

        return None

    rows = result.data or []

    return rows[0] if rows else None


def latest_observation(
    zone_code: str,
) -> Optional[Dict[str, Any]]:
    """The newest camera observation for a zone."""

    try:
        result = (
            get_supabase()
            .table(OBSERVATIONS)
            .select(
                "id,zone_code,value,confidence,observed_at,"
                "evidence_status"
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
    except Exception:
        logger.exception(
            "Failed to read the latest observation for '%s'",
            zone_code,
        )

        return None

    rows = result.data or []

    return rows[0] if rows else None


def zone_row(zone_code: str) -> Optional[Dict[str, Any]]:
    """The zone, carrying the capacity the engine needs."""

    try:
        result = (
            get_supabase()
            .table(ZONES)
            .select("id,code,name,zone_type,capacity")
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


def energy_picture(
    zone_code: str,
) -> Dict[str, Any]:
    """
    The zone's energy situation as it stands.

    The correlation run records a *judgement*; this records the
    *measurements* the judgement was made from. A what-if needs
    both: the run to justify why a condition exists, and the
    figures to model an intervention against.

    Returned with its timestamp so a caller can tell whether the
    figures still describe the zone, rather than assuming they
    do because they exist.
    """

    zone = zone_row(zone_code)

    if zone is None:
        return {}

    zone_id = zone.get("id")

    if not zone_id:
        return {}

    latest = _latest_metric(zone_id, "energy", 1)

    history = _latest_metric(zone_id, "energy", 200)

    values = sorted(
        value
        for value in (
            _as_float(row.get("value")) for row in history
        )
        if value is not None and value >= 0
    )

    # Three samples is the minimum for a median to describe
    # anything. Fewer is not a baseline, so the capacity-derived
    # nominal is used and the caller is told which happened.
    baseline_measured = len(values) >= 3

    expected = (
        values[len(values) // 2]
        if baseline_measured
        else _num(zone.get("capacity"), 0.0)
        * _NOMINAL_ENERGY_PER_CAPACITY
    )

    return {
        "capacity": _num(zone.get("capacity")),
        "energy_kw": (
            _as_float(latest[0].get("value"))
            if latest
            else None
        ),
        "expected_energy_kw": expected,
        "baseline_measured": baseline_measured,
        "energy_observed_at": (
            latest[0].get("timestamp") if latest else None
        ),
        "energy_samples": len(values),
    }


# Mirrors `app.core.correlation_rules.CorrelationConfig`. Declared
# here so the repository does not import the rules module, keeping
# the dependency running from storage upwards.
_NOMINAL_ENERGY_PER_CAPACITY = 0.05


def _latest_metric(
    zone_id: str,
    metric: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Recent readings of one metric for a zone.

    Keyed on `zone_id`, which is a UUID foreign key; the code
    lives on `zones`. Filtering by `zone_code` here would be
    rejected as an unknown column and would read as "no
    telemetry".
    """

    try:
        result = (
            get_supabase()
            .table(TELEMETRY)
            .select("value,timestamp")
            .eq("zone_id", zone_id)
            .eq("metric", metric)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception:
        logger.exception(
            "Failed to read '%s' telemetry", metric
        )

        return []

    return result.data or []


def _as_float(value) -> Optional[float]:
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return None if number != number else number


def _num(value, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def findings_by_name(
    run: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """
    Indexes a run's findings by check name.

    The findings blob is what lets the decision engine tell a
    stale telemetry feed from an unconfident camera, which is
    what makes a refusal explicable rather than opaque.
    """

    findings = run.get("findings")

    if not isinstance(findings, list):
        return {}

    indexed: Dict[str, Dict[str, Any]] = {}

    for item in findings:
        if isinstance(item, dict) and item.get("name"):
            indexed[str(item["name"])] = item

    return indexed


def correlation_context(
    zone_code: str,
) -> Dict[str, Any]:
    """
    Everything the decision engine needs about a zone's state.

    Assembled here so the service does not have to know which
    table holds which fact, and so a missing source is reported
    as `None` in one place rather than as an exception from
    three different queries.
    """

    run = latest_correlation_run(zone_code)
    observation = latest_observation(zone_code)
    zone = zone_row(zone_code)

    findings = findings_by_name(run or {})

    return {
        "correlation_run": run,
        "observation": observation,
        "zone": zone,
        "findings": findings,
        "energy": energy_picture(zone_code),
        # Derived from the recorded findings rather than
        # recomputed, so the confidence score reflects the
        # judgement that was actually recorded.
        "telemetry_fresh": bool(
            findings.get("energy_available", {}).get("passed")
        ),
        "vision_reliable": bool(
            findings.get("vision_reliable", {}).get("passed")
        ),
    }