"""
Correlation rules (Phase 8).

The evidence gate lives here as a set of small, individually
testable checks rather than as a single function, because the
whole value of the gate is that it can explain itself. When a
condition is downgraded, the response names which check failed
and why, so a human can tell "the camera is unsure" apart from
"the energy feed is dead".

Nothing in this module touches a database, a network or a model.
It takes numbers and timestamps and returns judgements about
them, which is what makes the gate deterministic and testable.

Deliberately not an LLM task. The engine decides what happened
and what qualifies; a language model may later explain that
decision. The PRD requires decisions to stay traceable to stored
calculations, and a generated narrative cannot be traced to
anything.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


# ============================================================
# CONFIGURATION
# ============================================================


@dataclass(frozen=True)
class CorrelationConfig:
    """
    Thresholds for the evidence gate.

    Frozen so a running engine cannot have its thresholds moved
    underneath it: a verdict that could change mid-request would
    not be reproducible from the correlation run it left behind.
    """

    # Telemetry older than this cannot support a finding. Thirty
    # seconds is comfortably longer than the ten-second flush
    # interval, so a healthy feed never trips this; a feed that
    # has stopped does, within half a minute.
    telemetry_max_age_seconds: int = 30

    # Vision freshness is held to a tighter bound than telemetry
    # because occupancy is the condition being judged. An old
    # count describes a room that may since have emptied.
    observation_max_age_seconds: int = 20

    # Below this the camera is guessing. A "no people" reading
    # at low confidence is not evidence of an empty room; it is
    # evidence that the model could not see well, and reading it
    # as empty is precisely the failure this gate exists to
    # prevent.
    minimum_vision_confidence: float = 0.55

    # A zone at or below this fraction of capacity counts as
    # low occupancy, which is a precondition for calling high
    # energy "waste during low occupancy".
    low_occupancy_ratio: float = 0.20

    # Energy must exceed this multiple of the zone's expected
    # draw before it is anomalous at all.
    energy_high_multiplier: float = 1.50

    co2_high_ppm: float = 1200.0

    temperature_high_c: float = 28.0

    # Fallback expectation used only when a zone has no energy
    # history to derive a baseline from. Expressed per unit of
    # zone capacity, so a large room is not expected to draw the
    # same as a small one.
    #
    # This is the weakest evidence path in the engine and is
    # documented as such: it is a nominal design figure, not a
    # measurement. Every other gate condition still applies.
    nominal_energy_kw_per_capacity: float = 0.05


DEFAULT_CORRELATION_CONFIG = CorrelationConfig()


# ============================================================
# EVIDENCE
# ============================================================


@dataclass(frozen=True)
class EvidenceCheck:
    """
    One gate condition and its outcome.

    `score` is 0..1 rather than a boolean so a partial failure
    can still be expressed. Today every check is pass or fail,
    but the field exists because collapsing confidence into a
    bit loses information a reviewer wants.
    """

    name: str

    passed: bool

    score: float

    reason: str


# Result statuses. Three only, and the wording is constrained
# on purpose: nothing here reports a confirmed physical fault.
#
# The PRD requires that modelled conditions are not represented
# as measured savings or proven leaks, so the strongest thing
# this engine may say is "candidate".
RESULT_NORMAL = "normal"
RESULT_NEEDS_REVIEW = "needs_review"
RESULT_CONFIRMED_CANDIDATE = "confirmed_candidate"


def _passed(name: str, reason: str) -> EvidenceCheck:
    return EvidenceCheck(
        name=name, passed=True, score=1.0, reason=reason
    )


def _failed(name: str, reason: str) -> EvidenceCheck:
    return EvidenceCheck(
        name=name, passed=False, score=0.0, reason=reason
    )


# ============================================================
# TIME
# ============================================================


def parse_timestamp(value) -> Optional[datetime]:
    """
    Parses a timestamp into an aware UTC datetime.

    Returns None rather than raising for anything unusable. A
    malformed timestamp is missing evidence, and missing evidence
    is something this engine reports; it is not an error to be
    raised at a caller who merely stored a timestamp badly.

    Accepts both ISO spellings of UTC. PostgREST has been seen
    returning `+00:00` where an upload sent `Z`, and a naive
    string is read as UTC to match the convention used by the
    telemetry and vision layers.
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()

        if not text:
            return None

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _age_seconds(
    moment: Optional[datetime],
    now: datetime,
) -> Optional[float]:
    if moment is None:
        return None

    return (now - moment).total_seconds()


# ============================================================
# OCCUPANCY
# ============================================================


def calculate_occupancy_ratio(
    occupancy: float,
    capacity: Optional[int],
) -> Optional[float]:
    """
    Occupancy as a fraction of zone capacity.

    Returns None when the ratio cannot be established, which is
    a different thing from a ratio of zero. An empty room at
    zero capacity and an unknown capacity look identical as a
    number but are not the same finding, and callers need to
    tell them apart: the first is normal, the second is missing
    evidence.
    """

    if capacity is None:
        return None

    try:
        capacity_value = float(capacity)
        occupancy_value = float(occupancy)
    except (TypeError, ValueError):
        return None

    # A capacity of zero makes the ratio undefined and a
    # negative one is nonsense. Both are treated as unknown
    # rather than clamped, so a misconfigured zone surfaces
    # instead of silently reporting a full or empty room.
    if capacity_value <= 0:
        return None

    return occupancy_value / capacity_value


def occupancy_state(
    ratio: Optional[float],
    config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> str:
    """
    Names the occupancy condition for the 3D twin.

    "potentially_unoccupied" rather than "unoccupied": a camera
    count is evidence about a room, not proof of it.
    """

    if ratio is None:
        return "unknown"

    if ratio > 1.0:
        return "over_capacity"

    if ratio <= config.low_occupancy_ratio:
        return "potentially_unoccupied"

    return "occupied"


# ============================================================
# GATE CHECKS
# ============================================================


def check_vision_evidence(
    occupancy: Optional[float],
    confidence: Optional[float],
    config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> EvidenceCheck:
    """
    Is the camera's reading trustworthy at all?
    """

    name = "vision_reliable"

    if occupancy is None:
        return _failed(
            name, "No camera count was available."
        )

    if confidence is None:
        return _failed(
            name, "The camera reported no confidence."
        )

    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return _failed(
            name, "The camera confidence was not a number."
        )

    # A confidence outside 0..1 means the detector or its
    # transport is broken. Treating it as 0 would at least fail
    # the gate, but naming the corruption is more useful than
    # reporting an ordinary low-confidence reading.
    if value < 0.0 or value > 1.0:
        return _failed(
            name,
            f"Camera confidence {value} is outside 0..1, so "
            "the reading cannot be trusted.",
        )

    if value < config.minimum_vision_confidence:
        return _failed(
            name,
            f"Camera confidence {value:.2f} is below the "
            f"{config.minimum_vision_confidence:.2f} needed to "
            "read an empty room as evidence.",
        )

    return _passed(
        name,
        f"Camera confidence {value:.2f} meets the "
        f"{config.minimum_vision_confidence:.2f} threshold.",
    )


def check_observation_freshness(
    observed_at: Optional[datetime],
    now: datetime,
    config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> EvidenceCheck:
    """
    Does the camera count describe the room as it is now?
    """

    name = "observation_fresh"

    age = _age_seconds(observed_at, now)

    if age is None:
        return _failed(
            name, "The observation carried no usable timestamp."
        )

    # A timestamp in the future means a clock disagreement, not
    # a very fresh reading. Letting it through would make broken
    # evidence look infinitely current, which is the exact
    # inversion the gate exists to prevent.
    if age < 0:
        return _failed(
            name,
            "The observation is timestamped in the future, so "
            "the source clock cannot be trusted.",
        )

    if age > config.observation_max_age_seconds:
        return _failed(
            name,
            f"The observation is {age:.0f}s old, beyond the "
            f"{config.observation_max_age_seconds}s limit.",
        )

    return _passed(
        name,
        f"The observation is {age:.0f}s old, within the "
        f"{config.observation_max_age_seconds}s limit.",
    )


def check_energy_evidence(
    energy_kw: Optional[float],
    timestamp: Optional[datetime] = None,
    now: Optional[datetime] = None,
    config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> EvidenceCheck:
    """
    Is there a usable energy reading, and is it current?

    Presence and freshness are checked together because a feed
    that has died is the more dangerous case: it does not report
    an error, it simply stops, and a stop looks exactly like a
    missing value to everything downstream.
    """

    name = "energy_available"

    if energy_kw is None:
        return _failed(
            name, "No energy telemetry was available."
        )

    try:
        value = float(energy_kw)
    except (TypeError, ValueError):
        return _failed(
            name, "The energy reading was not a number."
        )

    if value != value:  # NaN
        return _failed(
            name, "The energy reading was not a number."
        )

    if value < 0:
        return _failed(
            name,
            f"Energy was {value}, which is not physically "
            "possible and indicates a faulty meter.",
        )

    if timestamp is None or now is None:
        return _passed(
            name, f"Energy telemetry available at {value:.2f} kW."
        )

    age = _age_seconds(timestamp, now)

    if age is None:
        return _failed(
            name, "The energy reading carried no usable timestamp."
        )

    if age < 0:
        return _failed(
            name,
            "The energy reading is timestamped in the future, "
            "so the source clock cannot be trusted.",
        )

    if age > config.telemetry_max_age_seconds:
        return _failed(
            name,
            f"Energy telemetry is {age:.0f}s old, beyond the "
            f"{config.telemetry_max_age_seconds}s limit.",
        )

    return _passed(
        name,
        f"Energy telemetry is {value:.2f} kW and {age:.0f}s old, "
        f"within the {config.telemetry_max_age_seconds}s limit.",
    )


def check_schedule_active(
    schedule_active: bool,
) -> EvidenceCheck:
    """
    Is the zone supposed to be occupied right now?

    Outside operating hours a lit, powered room may be cleaning,
    maintenance, security or night operations, all of which draw
    energy legitimately. Calling that waste would flag the
    building for doing what it was told to do.
    """

    name = "schedule_active"

    if schedule_active:
        return _passed(
            name, "The zone is inside its operating schedule."
        )

    return _failed(
        name,
        "The zone is outside its operating schedule, so high "
        "energy may be legitimate cleaning, maintenance or "
        "security load.",
    )


def expected_energy_kw(
    energy_kw: Optional[float],
    baseline_kw: Optional[float] = None,
    capacity: Optional[int] = None,
    config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> Optional[float]:
    """
    The draw a healthy zone should be showing.

    A measured baseline is preferred and is always what a mature
    deployment supplies. The capacity-derived nominal exists only
    so a zone with no history yet can still be evaluated, and it
    is deliberately conservative: a nominal figure is a design
    assumption, not a measurement.
    """

    if baseline_kw is not None:
        try:
            baseline = float(baseline_kw)
        except (TypeError, ValueError):
            baseline = None

        if baseline is not None and baseline > 0:
            return baseline

    if capacity is not None:
        try:
            size = float(capacity)
        except (TypeError, ValueError):
            return None

        if size > 0:
            return size * config.nominal_energy_kw_per_capacity

    return None


def calculate_energy_ratio(
    energy_kw: Optional[float],
    expected_kw: Optional[float],
) -> Optional[float]:
    """
    Measured draw divided by expected draw.

    None when either side is missing. A ratio computed from a
    guessed expectation would be a fabricated number, so the
    engine refuses to produce one.
    """

    if energy_kw is None or expected_kw is None:
        return None

    try:
        measured = float(energy_kw)
        expected = float(expected_kw)
    except (TypeError, ValueError):
        return None

    if expected <= 0:
        return None

    return measured / expected


def check_energy_anomaly(
    ratio: Optional[float],
    config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> EvidenceCheck:
    """Is the energy draw high enough to be worth explaining?"""

    name = "energy_anomaly"

    if ratio is None:
        return _failed(
            name, "No energy ratio could be established."
        )

    if ratio < config.energy_high_multiplier:
        return _failed(
            name,
            f"Energy is {ratio:.2f}x expected, below the "
            f"{config.energy_high_multiplier:.2f}x threshold.",
        )

    return _passed(
        name,
        f"Energy is {ratio:.2f}x expected, above the "
        f"{config.energy_high_multiplier:.2f}x threshold.",
    )


def check_occupancy_low(
    ratio: Optional[float],
    config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> EvidenceCheck:
    """
    Is the zone actually empty enough for high energy to be waste?

    High energy in a full lecture hall is not waste; it is a
    lecture hall. This check is what keeps the engine from
    reporting the busiest room in the building as the biggest
    problem.
    """

    name = "occupancy_low"

    if ratio is None:
        return _failed(
            name,
            "Zone capacity is unknown, so occupancy cannot be "
            "judged low.",
        )

    if ratio > config.low_occupancy_ratio:
        return _failed(
            name,
            f"Occupancy is {ratio:.0%} of capacity, above the "
            f"{config.low_occupancy_ratio:.0%} treated as low.",
        )

    return _passed(
        name,
        f"Occupancy is {ratio:.0%} of capacity, at or below the "
        f"{config.low_occupancy_ratio:.0%} treated as low.",
    )


# ============================================================
# SCORING
# ============================================================


def calculate_evidence_score(
    checks: List[EvidenceCheck],
) -> float:
    """
    How much of the required evidence was actually present.

    Reported even when the gate fails, because a score of 43
    alongside `needs_review` tells a reviewer how far off the
    mark the evidence was. A flat zero would lose that.
    """

    if not checks:
        return 0.0

    passed = sum(1 for check in checks if check.passed)

    return round(100.0 * passed / len(checks), 2)


def calculate_confidence_score(
    confidence: Optional[float],
    ratio: Optional[float],
    config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> float:
    """
    How strongly the evidence supports the candidate.

    Weighted equally between how much better the camera was
    than the minimum required and how far the energy draw sat
    above the threshold. A finding that barely clears both bars
    is a weak finding, and this is what says so.

    Capped at 100 because the database column is bounded and a
    score above 100 would not be a stronger claim, just an
    invalid one.
    """

    reliability = 0.0
    strength = 0.0

    if confidence is not None:
        try:
            value = float(confidence)

            if 0.0 <= value <= 1.0:
                reliability = min(
                    1.0,
                    value / config.minimum_vision_confidence,
                )
        except (TypeError, ValueError):
            reliability = 0.0

    if ratio is not None:
        try:
            value = float(ratio)
            margin = config.energy_high_multiplier

            strength = min(
                1.0, max(0.0, (value - margin) / margin)
            )
        except (TypeError, ValueError, ZeroDivisionError):
            strength = 0.0

    score = 100.0 * (0.5 * reliability + 0.5 * strength)

    return round(max(0.0, min(100.0, score)), 2)


def blocking_check(
    checks: List[EvidenceCheck],
) -> Optional[EvidenceCheck]:
    """
    The first check that failed, which is the reason for the
    downgrade.

    Order matters and is meaningful: vision confidence comes
    first because without a trustworthy camera count there is no
    occupancy to reason about at all, and the gate would
    otherwise report "energy is stale" for a room nobody can
    see.
    """

    for check in checks:
        if not check.passed:
            return check

    return None