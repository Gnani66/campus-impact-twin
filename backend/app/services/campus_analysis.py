"""
Deterministic campus analysis for the copilot (Phase 13).

This module produces every fact the copilot will ever speak. The
model receives the result and restates it; it computes none of it.

Status is NOT recalculated here. Phase 12 already decides it in
`app.core.twin_rules` and publishes it through the twin snapshot.
Deriving it a second time would create two sources of truth for
criticality, which is precisely the class of bug this system has
been built to avoid since Phase 8. This module consumes the
snapshot and adds prioritisation on top of it.
"""

import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


# ============================================================
# SEVERITY WEIGHTS
# ============================================================

# Status to weight. Offline is included deliberately: a dead
# sensor is an operational problem in its own right, because
# nobody can see what the room is doing. It is weighted low
# because it says nothing about the room itself, but it is not
# zero because silence is not health.
SEVERITY_WEIGHTS = {
    "critical": 3.0,
    "warning": 2.0,
    "offline": 1.0,
    "normal": 0.0,
}


# ============================================================
# PRIORITY
# ============================================================


def people_affected(
    entity: Dict[str, Any],
) -> float:
    """
    How many people an entity's condition affects.

    Occupancy when measured, because that is the number of people
    actually exposed. Falls back to zero, which means an entity
    with no occupancy sensor is prioritised on severity alone
    rather than being guessed at.
    """

    metrics = entity.get("metrics") or {}

    value = metrics.get("occupancy")

    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def severity_of(entity: Dict[str, Any]) -> float:
    """The severity weight for an entity's backend status."""

    return SEVERITY_WEIGHTS.get(
        str(entity.get("status") or "").lower(), 0.0
    )


def calculate_priority(
    entity: Dict[str, Any],
    worst_people: float,
) -> float:
    """
    Operational priority, 0-100.

    severity * people, normalised against the most-affected
    entity on campus.

    The principle is that operational impact outranks sensor
    magnitude. A hot room holding five people and a milder room
    holding a hundred and fifty are not the same problem, and
    ranking by temperature alone would put the empty room first.

    WHAT IS DELIBERATELY MISSING: a duration factor. The
    specification proposes severity * people * duration * impact,
    and duration is the obvious next term. It is omitted because
    this system has no honest source for it: the twin snapshot
    carries the latest reading, not a history, and deriving a
    duration from that would mean inventing one. A factor
    labelled "duration" that is actually a guess would be worse
    than an absent factor, because it would look accounted for.

    Adding it later means reading an incident's `created_at` or a
    telemetry series, both of which are already stored.
    """

    severity = severity_of(entity)

    if severity <= 0:
        return 0.0

    people = people_affected(entity)

    # Normalising people by the worst-affected entity keeps the
    # result comparable across a campus of any size, and makes a
    # single room with nobody in it rank low regardless of how
    # hot it is.
    if worst_people <= 0:
        people_factor = 0.0
    else:
        people_factor = min(1.0, people / worst_people)

    # An entity with no occupancy reading is not treated as
    # having zero people: that would rank it below every measured
    # entity purely because a sensor is missing. It gets a
    # nominal half, which places it below an occupied room and
    # above an empty one.
    if people <= 0:
        people_factor = 0.5

    raw = severity * people_factor * 100.0

    return round(min(100.0, max(0.0, raw)), 2)


def rank_entities(
    entities: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Orders entities by operational priority, highest first.

    Ties break on the backend status and then the code, so the
    ordering is deterministic and a campus with two equally
    affected rooms does not reshuffle between refreshes.
    """

    if not entities:
        return []

    worst_people = max(
        (people_affected(entity) for entity in entities),
        default=0.0,
    )

    enriched = []

    for entity in entities:
        row = dict(entity)

        row["priority"] = calculate_priority(
            entity, worst_people
        )
        row["people_affected"] = people_affected(entity)
        row["severity_weight"] = severity_of(entity)

        enriched.append(row)

    return sorted(
        enriched,
        key=lambda row: (
            -row["priority"],
            -row["severity_weight"],
            str(row.get("code") or ""),
        ),
    )


# ============================================================
# SNAPSHOT
# ============================================================


def build_snapshot(
    twin_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Turns the twin snapshot into a prioritised campus brief.

    This is the deterministic analysis the copilot reasons over.
    It is pure: same snapshot in, same brief out, with no
    database access and no model involvement.
    """

    entities = twin_snapshot.get("entities") or []

    ranked = rank_entities(list(entities))

    counts = {
        "normal": 0,
        "warning": 0,
        "critical": 0,
        "offline": 0,
    }

    for entity in entities:
        status = str(entity.get("status") or "").lower()

        if status in counts:
            counts[status] += 1

    needs_attention = [
        row for row in ranked if row["priority"] > 0
    ]

    top = (
        needs_attention[0]
        if needs_attention
        else (ranked[0] if ranked else None)
    )

    critical = [
        row
        for row in ranked
        if row.get("status") == "critical"
    ]
    warnings = [
        row
        for row in ranked
        if row.get("status") == "warning"
    ]
    offline = [
        row
        for row in ranked
        if row.get("status") == "offline"
    ]

    caveats = []

    if offline:
        caveats.append(
            f"{len(offline)} entity/entities have no live "
            "telemetry. Their state is unknown, not healthy."
        )

    if not entities:
        caveats.append(
            "No campus entities are configured."
        )

    logger.info(
        "Campus snapshot: %d entities, %d critical, %d warning, "
        "%d offline, top=%s",
        len(entities),
        len(critical),
        len(warnings),
        len(offline),
        (top or {}).get("code"),
    )

    return {
        "total_entities": len(entities),
        "counts": counts,
        "critical_issues": critical,
        "warnings": warnings,
        "offline": offline,
        "ranked_entities": needs_attention or ranked,
        "entities": list(entities),
        "top_priority": top,
        "caveats": caveats,
    }


def entity_brief(
    entity: Dict[str, Any],
    worst_people: Optional[float] = None,
) -> Dict[str, Any]:
    """
    A single entity with its priority attached.

    Priority for one entity is computed against the campus-wide
    worst case, so a number shown beside a single room means the
    same thing whether or not other rooms are currently listed.
    """

    if worst_people is None:
        worst_people = max(
            (
                people_affected(row)
                for row in (entity, )
            ),
            default=0.0,
        )

    row = dict(entity)

    row["priority"] = calculate_priority(entity, worst_people)
    row["people_affected"] = people_affected(entity)
    row["severity_weight"] = severity_of(entity)

    return row