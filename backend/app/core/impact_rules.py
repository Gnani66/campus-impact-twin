"""
Impact rules (Phase 9).

Impact is multi-dimensional on purpose. An intervention that
saves 3 kW and one that saves 3 kW *and* 400 litres of water are
not equivalent, and neither is comparable to a third that costs
nothing and saves nothing.

Every weight here is a product assumption, not a physical law.
They live in a frozen dataclass so they can be shown, argued
with and changed deliberately, rather than buried in the middle
of a scoring function where nobody would find them.

Nothing in this module touches a database. Raw quantities in
operational units go in, 0-100 scores come out, and the same
inputs always produce the same output.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


# ============================================================
# CONFIGURATION
# ============================================================


@dataclass(frozen=True)
class ImpactWeights:
    """
    How much each dimension contributes to the impact score.

    Energy dominates because it is the resource this deployment
    actually meters and the one the evidence gate reasons about
    most directly. The remainder keep water, waste and carbon
    from being treated as decoration. These are engineering
    judgements about this product, not universal constants.
    """

    energy: float = 0.35
    water: float = 0.20
    waste: float = 0.15
    co2: float = 0.15
    business_priority: float = 0.15


@dataclass(frozen=True)
class ImpactReferences:
    """
    Reference magnitudes used to normalise raw quantities to
    0-100.

    A reference is the amount that scores 100. These are
    deliberately round and deliberately configurable: they say
    "5 kW is a large saving for one zone in this building", not
    anything about physics. Choosing them is a product decision
    and the numbers below are placeholders that should be
    calibrated against real deployments.
    """

    energy_kw: float = 5.0
    water_litres: float = 500.0
    waste_kg: float = 50.0
    co2_kg: float = 100.0

    # Cost reference used when a simulation supplies no budget.
    # Falling back to a real figure rather than to "free" keeps
    # a missing budget from making every option look cheap.
    default_cost: float = 50000.0


DEFAULT_IMPACT_WEIGHTS = ImpactWeights()
DEFAULT_IMPACT_REFERENCES = ImpactReferences()


# Below this the impact score is treated as noise. It exists so
# a zero-cost intervention that changes nothing cannot earn a
# perfect cost-efficiency score.
MIN_MEANINGFUL_IMPACT = 1.0


# How disruption levels map to a score. Stored alongside the
# level itself so a UI can explain the mapping instead of
# showing a bare number nobody can interpret.
DISRUPTION_SCORES: Dict[str, float] = {
    "low": 90.0,
    "medium": 60.0,
    "high": 25.0,
}

DEFAULT_DISRUPTION_SCORE = 25.0


# Confidence is drawn from four equally weighted sources. Each
# answers a different question: can we see, is the feed alive,
# do we know what normal looks like, and how well is this
# particular action understood.
CONFIDENCE_WEIGHTS: Dict[str, float] = {
    "vision": 0.25,
    "telemetry": 0.25,
    "baseline": 0.25,
    "intervention": 0.25,
}

# A baseline derived from measured history is worth full
# credit. One derived from zone capacity is a design
# assumption and cannot earn the same.
BASELINE_MEASURED_CREDIT = 1.0
BASELINE_NOMINAL_CREDIT = 0.4


# ============================================================
# VALUE PROVENANCE
# ============================================================

# Every projected number carries where it came from. The PRD
# requires modelled outcomes to be labelled as modelled, so a
# UI can never render "you will save 2.1 kW" for a figure that
# is a projection.
VALUE_MEASURED = "measured"
VALUE_MODELED = "modeled"
VALUE_ESTIMATED = "estimated"
VALUE_SIMULATED = "simulated"

VALID_VALUE_TYPES = (
    VALUE_MEASURED,
    VALUE_MODELED,
    VALUE_ESTIMATED,
    VALUE_SIMULATED,
)


# ============================================================
# HELPERS
# ============================================================


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Constrains a score to a range, tolerating bad input."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return low

    if number != number:  # NaN
        return low

    # Infinity is clamped rather than propagated: an unbounded
    # score would silently win every comparison.
    if number == float("inf"):
        return high

    if number == float("-inf"):
        return low

    return max(low, min(high, number))


def normalise(
    value: Optional[float],
    reference: float,
) -> float:
    """
    Scales a raw quantity onto 0-100 against a reference.

    Returns 0 rather than dividing by zero when the reference
    is missing or nonsensical.
    """

    if value is None or reference is None or reference <= 0:
        return 0.0

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    if number != number:
        return 0.0

    # A negative saving is not a saving. Clamping at zero stops
    # a projection that made things worse from dragging the
    # score below the floor of "did nothing".
    if number <= 0:
        return 0.0

    return clamp(100.0 * number / reference)


# ============================================================
# IMPACT
# ============================================================


def calculate_impact_score(
    energy_reduction: float,
    water_reduction: float,
    waste_reduction: float,
    co2_reduction: float,
    business_priority: float,
    weights: ImpactWeights = DEFAULT_IMPACT_WEIGHTS,
    references: ImpactReferences = DEFAULT_IMPACT_REFERENCES,
) -> float:
    """
    Combines every resource dimension into one 0-100 score.

    Each dimension is normalised against its own reference
    first, because kW and litres cannot be added to each
    other. A dimension with no measurement scores zero rather
    than being assumed: the metric may well be irrelevant to
    this intervention, and inventing a value would invent
    impact.
    """

    parts = {
        "energy": normalise(
            energy_reduction, references.energy_kw
        ),
        "water": normalise(
            water_reduction, references.water_litres
        ),
        "waste": normalise(
            waste_reduction, references.waste_kg
        ),
        "co2": normalise(co2_reduction, references.co2_kg),
        # Already 0..1 by construction.
        "business_priority": clamp(
            business_priority * 100.0
        ),
    }

    score = sum(
        parts[name] * weight
        for name, weight in (
            ("energy", weights.energy),
            ("water", weights.water),
            ("waste", weights.waste),
            ("co2", weights.co2),
            ("business_priority", weights.business_priority),
        )
    )

    return round(clamp(score), 2)


def disruption_score(
    disruption_level: Optional[str],
) -> float:
    """
    Maps a disruption level onto a score.

    An unknown level scores conservatively rather than
    optimistically. A level the engine does not recognise is a
    gap in the library, and guessing in the intervention's
    favour would be exactly the wrong direction to err.
    """

    if not disruption_level:
        return DEFAULT_DISRUPTION_SCORE

    return DISRUPTION_SCORES.get(
        str(disruption_level).lower(),
        DEFAULT_DISRUPTION_SCORE,
    )


def calculate_confidence_score(
    vision_confidence: Optional[float],
    telemetry_fresh: bool,
    baseline_measured: bool,
    intervention_confidence: Optional[float],
    baseline_credit: float = None,
) -> float:
    """
    How much the evidence behind this decision can be trusted.

    Four equally weighted questions: can the camera see, is the
    telemetry alive, is "normal" actually known, and is this
    action well understood. An aggressive intervention backed
    by three good answers and one bad one must not outrank a
    gentle one backed by four.
    """

    credit = (
        BASELINE_MEASURED_CREDIT
        if baseline_measured
        else (
            BASELINE_NOMINAL_CREDIT
            if baseline_credit is None
            else baseline_credit
        )
    )

    parts = {
        "vision": clamp(_unit(vision_confidence) * 100.0),
        "telemetry": 100.0 if telemetry_fresh else 0.0,
        "baseline": clamp(credit * 100.0),
        "intervention": clamp(
            _unit(intervention_confidence) * 100.0
        ),
    }

    score = sum(
        parts[name] * weight
        for name, weight in CONFIDENCE_WEIGHTS.items()
    )

    return round(clamp(score), 2)


def _unit(value: Optional[float]) -> float:
    """Coerces a 0..1 confidence, rejecting nonsense."""

    if value is None:
        return 0.0

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    if number != number:
        return 0.0

    # A confidence outside 0..1 means a broken producer. Treat it
    # as no confidence at all rather than clamping upward.
    if number < 0.0 or number > 1.0:
        return 0.0

    return number


def calculate_cost_efficiency(
    impact_score: float,
    cost: float,
    cost_reference: Optional[float] = None,
    references: ImpactReferences = DEFAULT_IMPACT_REFERENCES,
) -> float:
    """
    How much impact is bought per unit of money.

    The trap this avoids is treating zero cost as automatically
    best. A free intervention that changes nothing is worse than
    an expensive one that works, so the impact guard is applied
    BEFORE the zero-cost shortcut, not after.

    Beyond that, efficiency decays hyperbolically with cost
    rather than linearly: the difference between free and cheap
    matters far more than the difference between expensive and
    very expensive, and a linear penalty would distort the
    ranking accordingly.
    """

    impact = clamp(impact_score)

    if impact < MIN_MEANINGFUL_IMPACT:
        # Nothing worth buying, whatever it costs.
        return 0.0

    try:
        price = float(cost)
    except (TypeError, ValueError):
        price = 0.0

    if price < 0:
        # A negative cost is a modelling error, not a bargain.
        return 0.0

    if price == 0:
        return 100.0

    reference = (
        cost_reference
        if cost_reference and cost_reference > 0
        else references.default_cost
    )

    normalised_cost = clamp(100.0 * price / reference)

    return round(
        clamp(impact * (1.0 - normalised_cost / 100.0)), 2
    )


# ============================================================
# OVERALL SCORE
# ============================================================


@dataclass(frozen=True)
class OverallWeights:
    """
    How the dimensions combine into a ranking score.

    Impact leads and confidence is second, because a large
    effect believed on thin evidence and a modest effect
    believed on strong evidence are both worse than a large
    effect believed on strong evidence. Feasibility follows,
    then cost and disruption, which refine rather than decide.
    """

    impact: float = 0.35
    confidence: float = 0.25
    feasibility: float = 0.20
    cost_efficiency: float = 0.10
    disruption: float = 0.10


DEFAULT_OVERALL_WEIGHTS = OverallWeights()


def calculate_overall_score(
    impact_score: float,
    confidence_score: float,
    feasibility_score: float,
    cost_efficiency_score: float,
    disruption_value: float,
    weights: OverallWeights = DEFAULT_OVERALL_WEIGHTS,
) -> float:
    """
    The ranking score for one option.

    Every input is already 0-100, so this is a weighted mean
    rather than a calculation with units. Weights sum to 1,
    which is asserted by the tests; if they ever stop summing
    to 1 the score would silently change scale and every
    previously stored comparison would become incomparable.
    """

    parts = (
        (impact_score, weights.impact),
        (confidence_score, weights.confidence),
        (feasibility_score, weights.feasibility),
        (cost_efficiency_score, weights.cost_efficiency),
        (disruption_value, weights.disruption),
    )

    score = sum(
        clamp(value) * weight for value, weight in parts
    )

    return round(clamp(score), 2)


# ============================================================
# STRESS TESTING
# ============================================================


def stress_band(
    expected: Optional[float],
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    baseline_percent: Optional[float] = None,
    max_percent: Optional[float] = None,
) -> Tuple[float, float, float]:
    """
    Returns (worst, expected, best) for a projected value.

    Bounded by explicit minimum/maximum when the intervention
    supplies them, and otherwise derived from the reduction
    assumptions, which describe how far the estimate can move
    in either direction.

    When no basis for a spread exists the three values are
    equal. That is honest: the model genuinely has no opinion,
    and the caller must say so rather than presenting a
    zero-width band that reads as certainty.
    """

    if expected is None:
        return 0.0, 0.0, 0.0

    try:
        centre = float(expected)
    except (TypeError, ValueError):
        return 0.0, 0.0, 0.0

    low = _coerce(minimum)
    high = _coerce(maximum)

    if low is None or high is None:
        derived_low, derived_high = _spread_from_assumptions(
            centre, baseline_percent, max_percent
        )

        low = derived_low if low is None else low
        high = derived_high if high is None else high

    # The band must be ordered even if the stored values are
    # not, or a caller could be handed a best case below the
    # expected case.
    low = min(low, centre)
    high = max(high, centre)

    return (
        round(max(0.0, low), 4),
        round(max(0.0, centre), 4),
        round(max(0.0, high), 4),
    )


def _spread_from_assumptions(
    expected: float,
    baseline_percent: Optional[float],
    max_percent: Optional[float],
) -> Tuple[float, float]:
    """
    Derives a band from the reduction percentages.

    A model claiming a 30% baseline reduction that might reach
    50% can plausibly deliver as little as 30/50 of the
    estimate, and as much as 50/30. The ratios are clamped so
    a zero or negative maximum cannot produce nonsense.
    """

    base = _coerce(baseline_percent)
    peak = _coerce(max_percent)

    if base is None or peak is None or peak <= 0 or base <= 0:
        return expected, expected

    low = expected * (base / peak)
    high = expected * (peak / base)

    # A ratio beyond 3x either way implies the model is not
    # really bounding its own uncertainty.
    return (
        max(low, expected / 3.0),
        min(high, expected * 3.0),
    )


def _coerce(value) -> Optional[float]:
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number != number:
        return None

    return number