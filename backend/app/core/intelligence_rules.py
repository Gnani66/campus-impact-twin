"""
Deterministic campus intelligence rules.

Every rule here is a pure function of observed telemetry plus
the context needed to interpret it. No model, no randomness, no
network. The same inputs always produce the same verdict, which
is what makes an incident defensible: a reviewer can recompute
the decision by hand from the evidence.

A rule returns a `RuleResult` when it fires and `None` when it
does not. Callers treat `None` as "this rule is not applicable
right now" rather than "everything is fine".

Categories are constrained by the `category` CHECK constraint on
`incidents`: energy, environment, occupancy, water, equipment,
safety, maintenance, other.
"""

import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RuleResult:
    """
    A single rule firing.

    `evidence` holds rule-specific measurements. The intelligence
    service adds the sensor, location and reading that triggered
    it before the incident is persisted.
    """

    triggered: bool
    category: str
    severity: str
    title: str
    description: str
    impact_score: float
    confidence_score: float
    evidence: List[Dict[str, Any]] = field(
        default_factory=list
    )


# ============================================================
# THRESHOLDS
#
# Indoor air quality and comfort limits. CO2 is the clearest
# proxy for ventilation adequacy in an occupied room; the
# temperature and humidity bounds are standard comfort limits
# for a lecture theatre.
# ============================================================

TEMPERATURE_HIGH = 28.0
TEMPERATURE_CRITICAL = 32.0

HUMIDITY_LOW = 30.0
HUMIDITY_HIGH = 70.0

CO2_HIGH = 1200.0
CO2_CRITICAL = 1800.0

ENERGY_MULTIPLIER_HIGH = 1.7
ENERGY_MULTIPLIER_CRITICAL = 2.3

# An energy multiplier needs an absolute floor, otherwise a
# 0.4 kW zone trips the rule on a 0.2 kW baseline where the
# difference is noise rather than waste.
ENERGY_MULTIPLIER_MIN_EXCESS_KW = 0.5

OCCUPANCY_OVER_CAPACITY_RATIO = 1.0


# ============================================================
# SCORING HELPERS
# ============================================================

# Confidence is high by construction: these rules read a single
# validated measurement and compare it to a fixed bound. It is
# not 100 because a sensor can be mis-sited or mis-calibrated.
RULE_BASE_CONFIDENCE = 96.0


def _clamp(
    value: float,
    low: float,
    high: float,
) -> float:
    return max(low, min(value, high))


def _progress(
    value: float,
    low: float,
    high: float,
) -> float:
    """
    Position of `value` between `low` and `high` as 0..1.

    Used to scale impact, so an incident that barely crosses a
    threshold scores far below one that is far past it.
    """

    if high <= low:
        return 1.0

    return _clamp(
        (value - low) / (high - low),
        0.0,
        1.0,
    )


def _impact_for(
    severity: str,
    progress: float,
) -> float:
    """
    Maps severity and threshold progress onto 0..100.

    A reading exactly on the warning threshold is a real finding
    but a minor one, so each severity band starts well above the
    previous band's end rather than at zero.
    """

    band = {
        "low": (25.0, 50.0),
        "medium": (40.0, 65.0),
        "high": (60.0, 85.0),
        "critical": (80.0, 100.0),
    }.get(severity, (40.0, 70.0))

    low, high = band

    return round(
        low + (high - low) * progress,
        2,
    )


def _confidence_for(
    severity: str,
    supporting: int,
) -> float:
    """
    Deterministic confidence.

    Starts from the rule base and loses points when the
    interpretation depends on context rather than on the
    measurement alone, and when the severity is the most extreme
    band, where a false positive is most costly.
    """

    score = RULE_BASE_CONFIDENCE

    # One supporting cross-check (occupancy, baseline) is worth a
    # small discount because the reading itself is unchanged.
    if supporting < 1:
        score -= 8.0

    if severity == "critical":
        score -= 4.0

    return round(_clamp(score, 0.0, 100.0), 2)


def _describe_occupancy(
    occupancy: float,
) -> str:
    return (
        f"{occupancy:.0f} people present"
    )


# ============================================================
# RULES
# ============================================================


def evaluate_temperature(
    value: float,
    occupancy: Optional[float] = None,
    capacity: Optional[int] = None,
) -> Optional[RuleResult]:
    """
    Overheating.

    Requires occupancy. An empty zone at 30 C is a closed door,
    not an environmental failure, and firing on it would fill
    the incident table at 02:00 every night.
    """

    if value < TEMPERATURE_HIGH:
        return None

    if occupancy is None or occupancy <= 0:
        return None

    critical = value >= TEMPERATURE_CRITICAL

    severity = "critical" if critical else "high"

    progress = (
        1.0
        if critical
        else _progress(
            value,
            TEMPERATURE_HIGH,
            TEMPERATURE_CRITICAL,
        )
    )

    evidence: Dict[str, Any] = {
        "rule": (
            "temperature_critical"
            if critical
            else "temperature_high"
        ),
        "temperature_c": round(value, 2),
        "threshold_c": (
            TEMPERATURE_CRITICAL
            if critical
            else TEMPERATURE_HIGH
        ),
        "occupancy": round(float(occupancy), 2),
    }

    if capacity:
        evidence["capacity"] = capacity
        evidence["occupancy_ratio"] = round(
            float(occupancy) / capacity,
            3,
        )

    return RuleResult(
        triggered=True,
        category="environment",
        severity=severity,
        title="Overheating in an occupied zone",
        description=(
            f"Temperature is {value:.1f} C, at or above the "
            f"{'critical ' if critical else ''}threshold of "
            f"{TEMPERATURE_CRITICAL if critical else TEMPERATURE_HIGH:.0f} C, "
            f"with {_describe_occupancy(occupancy)}."
        ),
        impact_score=_impact_for(severity, progress),
        confidence_score=_confidence_for(
            severity, supporting=1
        ),
        evidence=[evidence],
    )


def evaluate_humidity(
    value: float,
    occupancy: Optional[float] = None,
    capacity: Optional[int] = None,
) -> Optional[RuleResult]:
    """
    Humidity outside the comfort band, in either direction.
    """

    if HUMIDITY_LOW <= value <= HUMIDITY_HIGH:
        return None

    if occupancy is not None and occupancy <= 0:
        return None

    high = value > HUMIDITY_HIGH

    severity = "high" if high else "medium"

    progress = (
        _progress(value, HUMIDITY_HIGH, 90.0)
        if high
        else _progress(HUMIDITY_LOW, value, 10.0)
    )

    direction = "high" if high else "low"

    return RuleResult(
        triggered=True,
        category="environment",
        severity=severity,
        title=f"Humidity {direction} in an occupied zone",
        description=(
            f"Relative humidity is {value:.1f}%, outside the "
            f"{HUMIDITY_LOW:.0f}-{HUMIDITY_HIGH:.0f}% comfort "
            f"band."
            + (
                f" Zone is {_describe_occupancy(occupancy)}."
                if occupancy
                else ""
            )
        ),
        impact_score=_impact_for(severity, progress),
        confidence_score=_confidence_for(
            severity, supporting=1
        ),
        evidence=[
            {
                "rule": f"humidity_{direction}",
                "humidity_pct": round(value, 2),
                "threshold_pct": (
                    HUMIDITY_HIGH if high else HUMIDITY_LOW
                ),
            }
        ],
    )


def evaluate_co2(
    value: float,
    occupancy: Optional[float] = None,
    capacity: Optional[int] = None,
) -> Optional[RuleResult]:
    """
    Indoor air quality.

    CO2 above the ambient background means occupants are
    generating it and ventilation is not removing it fast enough.
    Occupancy is the natural cross-check: a high CO2 reading in
    a full hall is expected, and a high reading in an empty room
    points at the sensor rather than the ventilation.
    """

    if value < CO2_HIGH:
        return None

    critical = value >= CO2_CRITICAL

    severity = "critical" if critical else "high"

    progress = (
        1.0
        if critical
        else _progress(value, CO2_HIGH, CO2_CRITICAL)
    )

    evidence: Dict[str, Any] = {
        "rule": (
            "co2_critical" if critical else "co2_high"
        ),
        "co2_ppm": round(value, 1),
        "threshold_ppm": (
            CO2_CRITICAL if critical else CO2_HIGH
        ),
    }

    if occupancy is not None:
        evidence["occupancy"] = round(float(occupancy), 2)

    if capacity:
        evidence["capacity"] = capacity

    return RuleResult(
        triggered=True,
        category="environment",
        severity=severity,
        title="Poor indoor air quality",
        description=(
            f"CO2 concentration is {value:.0f} ppm"
            + (
                f" with {_describe_occupancy(occupancy)}."
                if occupancy is not None
                else "."
            )
        ),
        impact_score=_impact_for(severity, progress),
        confidence_score=_confidence_for(
            severity, supporting=1
        ),
        evidence=[evidence],
    )


def evaluate_energy(
    value: float,
    baseline_kw: Optional[float] = None,
    occupancy: Optional[float] = None,
    capacity: Optional[int] = None,
) -> Optional[RuleResult]:
    """
    Energy draw above what this zone normally uses.

    Without a baseline there is nothing to compare against, so
    the rule declines rather than guessing. The absolute excess
    floor keeps low-power zones from tripping on their own
    noise.
    """

    if baseline_kw is None or baseline_kw <= 0:
        return None

    multiplier = value / baseline_kw

    if multiplier < ENERGY_MULTIPLIER_HIGH:
        return None

    excess = value - baseline_kw

    if excess < ENERGY_MULTIPLIER_MIN_EXCESS_KW:
        return None

    critical = multiplier >= ENERGY_MULTIPLIER_CRITICAL

    severity = (
        "critical" if critical else "medium"
    )

    progress = (
        1.0
        if critical
        else _progress(
            multiplier,
            ENERGY_MULTIPLIER_HIGH,
            ENERGY_MULTIPLIER_CRITICAL,
        )
    )

    evidence: Dict[str, Any] = {
        "rule": (
            "energy_critical"
            if critical
            else "energy_above_baseline"
        ),
        "energy_kw": round(value, 3),
        "baseline_kw": round(baseline_kw, 3),
        "multiplier": round(multiplier, 2),
    }

    if occupancy is not None:
        evidence["occupancy"] = round(float(occupancy), 2)

        if occupancy <= 0:
            evidence[
                "note"
            ] = (
                "baseline power with no occupants present"
            )

    return RuleResult(
        triggered=True,
        category="energy",
        severity=severity,
        title="Energy draw above zone baseline",
        description=(
            f"Zone is drawing {value:.2f} kW against a "
            f"baseline of {baseline_kw:.2f} kW "
            f"({multiplier:.1f}x)"
            + (
                f" with {_describe_occupancy(occupancy)}."
                if occupancy is not None
                else "."
            )
        ),
        impact_score=_impact_for(severity, progress),
        confidence_score=_confidence_for(
            severity, supporting=1
        ),
        evidence=[evidence],
    )


def evaluate_occupancy(
    value: float,
    capacity: Optional[int] = None,
) -> Optional[RuleResult]:
    """
    Headcount above the zone's rated capacity.
    """

    if capacity is None or capacity <= 0:
        return None

    if value <= capacity * OCCUPANCY_OVER_CAPACITY_RATIO:
        return None

    progress = _progress(
        value,
        capacity,
        capacity * 2.0,
    )

    return RuleResult(
        triggered=True,
        category="occupancy",
        severity="medium",
        title="Zone over capacity",
        description=(
            f"{value:.0f} people are present against a rated "
            f"capacity of {capacity}."
        ),
        impact_score=_impact_for("medium", progress),
        confidence_score=_confidence_for(
            "medium", supporting=1
        ),
        evidence=[
            {
                "rule": "occupancy_over_capacity",
                "occupancy": round(float(value), 2),
                "capacity": capacity,
            }
        ],
    )


# Dispatch table keyed by the `metric` recorded in
# telemetry_readings. Each entry receives the reading value plus
# the context bundle resolved by the intelligence service.
EVALUATORS = {
    "temperature": evaluate_temperature,
    "humidity": evaluate_humidity,
    "co2": evaluate_co2,
    "energy": evaluate_energy,
    "occupancy": evaluate_occupancy,
}


def evaluate_metric(
    metric: str,
    value: float,
    context: Dict[str, Any],
) -> Optional[RuleResult]:
    """
    Runs the rule for `metric`, if one exists.

    Only the keyword arguments a rule actually declares are
    passed. The context bundle is shared across rules so callers
    can build it once, but the rules accept different subsets:
    `evaluate_occupancy` takes the headcount as its first
    argument, for instance, so forwarding `occupancy=` to it
    would be a TypeError.

    Unknown metrics return None rather than raising, so adding a
    sensor type in a later phase cannot break ingestion.
    """

    evaluator = EVALUATORS.get(metric)

    if evaluator is None:
        return None

    accepted = inspect.signature(evaluator).parameters

    kwargs = {
        key: item
        for key, item in context.items()
        if key in accepted
    }

    return evaluator(value, **kwargs)
