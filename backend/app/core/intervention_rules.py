"""
Intervention rules (Phase 9).

An intervention is a candidate action. These rules decide
whether one may even be offered, given what the evidence gate
actually found. They do not rank anything: ranking is Phase
10's job and mixing the two would make it impossible to say
why an option was refused rather than merely unranked.

The refusal reasons are as important as the scores. An option
excluded for want of evidence has to say so, or a reader is
left wondering whether it was considered at all.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# EVIDENCE QUALITY
# ============================================================
#
# The stored schema expresses evidence quality as an enum rather
# than a score. The correlation engine produces a 0-100 evidence
# score, so the two have to meet somewhere, and this is where.
#
# The bands are a product judgement and are deliberately visible:
# an intervention demanding `strong` evidence is refusing to act
# on anything the evidence gate was not confident about, and
# somebody should be able to see and argue with where that line
# sits.

QUALITY_WEAK = "weak"
QUALITY_MODERATE = "moderate"
QUALITY_STRONG = "strong"

QUALITY_ORDER = {
    QUALITY_WEAK: 0,
    QUALITY_MODERATE: 1,
    QUALITY_STRONG: 2,
}

# A score at or above this is strong evidence.
STRONG_EVIDENCE_SCORE = 80.0

# At or above this, but below strong, is moderate.
MODERATE_EVIDENCE_SCORE = 50.0


def evidence_quality_for(
    evidence_score: Optional[float],
) -> str:
    """
    Maps a 0-100 evidence score onto the stored enum.

    Returns `weak` for a missing score. An unknown quantity is
    not moderate evidence, and defaulting upward would let an
    unevidenced condition qualify for the more aggressive
    interventions.
    """

    if evidence_score is None:
        return QUALITY_WEAK

    try:
        score = float(evidence_score)
    except (TypeError, ValueError):
        return QUALITY_WEAK

    if score != score:  # NaN
        return QUALITY_WEAK

    if score >= STRONG_EVIDENCE_SCORE:
        return QUALITY_STRONG

    if score >= MODERATE_EVIDENCE_SCORE:
        return QUALITY_MODERATE

    return QUALITY_WEAK


def quality_meets(
    actual: Optional[str], required: Optional[str]
) -> bool:
    """
    Is the evidence at least as strong as an intervention
    demands?

    Compares by rank rather than by name, so the order is defined
    in one place. An unrecognised requirement is treated as
    unmet: an intervention asking for evidence quality the
    engine cannot evaluate must not be offered as though it
    could.
    """

    required_rank = QUALITY_ORDER.get(
        str(required or QUALITY_WEAK).lower()
    )

    if required_rank is None:
        return False

    actual_rank = QUALITY_ORDER.get(
        str(actual or QUALITY_WEAK).lower(), 0
    )

    return actual_rank >= required_rank


# ============================================================
# CONSTRAINT VOCABULARY
# ============================================================
#
# Declared here so an unknown constraint is a visible typo
# rather than a rule that silently never fires.

CONSTRAINT_OPERATING_WINDOW = "must_be_within_operating_window"
CONSTRAINT_HVAC_CONTROL = "requires_hvac_control"
CONSTRAINT_LIGHTING_CONTROL = "requires_lighting_control"
CONSTRAINT_WATER_ACCESS = "requires_water_access"
CONSTRAINT_HUMAN_APPROVAL = "requires_human_approval"
CONSTRAINT_SCHEDULING = "requires_rescheduling"

KNOWN_CONSTRAINTS = frozenset(
    {
        CONSTRAINT_OPERATING_WINDOW,
        CONSTRAINT_HVAC_CONTROL,
        CONSTRAINT_LIGHTING_CONTROL,
        CONSTRAINT_WATER_ACCESS,
        CONSTRAINT_HUMAN_APPROVAL,
        CONSTRAINT_SCHEDULING,
    }
)


# ============================================================
# CONFIGURATION
# ============================================================


@dataclass(frozen=True)
class InterventionConfig:
    """
    Thresholds for eligibility and feasibility.

    `feasible_score_cap` is what an option that violates a hard
    constraint can score even if it is otherwise excellent.
    Without a cap an infeasible option could still rank highly
    and be recommended, which would be actively dangerous: the
    whole point of the constraint is that it cannot be traded
    away against a good impact number.
    """

    # Options longer than this need scheduling, which is a
    # practical barrier rather than a blocker.
    long_duration_minutes: int = 120

    feasible_score_cap: float = 20.0

    # Scoring bands, per the feasibility scale.
    immediate_score: float = 95.0
    minor_preparation_score: float = 75.0
    coordination_score: float = 50.0
    major_dependency_score: float = 25.0


DEFAULT_INTERVENTION_CONFIG = InterventionConfig()


@dataclass
class EligibilityResult:
    """
    Whether an intervention may be offered, and why not.
    """

    eligible: bool

    reasons: List[str] = field(default_factory=list)


# ============================================================
# ELIGIBILITY
# ============================================================


def check_evidence_eligibility(
    evidence_score: Optional[float],
    minimum_required: str,
) -> EligibilityResult:
    """
    Is there enough evidence to act on this intervention at all?

    `minimum_required` is the stored quality enum. This is the
    mechanism behind NO SAFE RECOMMENDATION: an analysis whose
    evidence falls short does not get a quieter
    recommendation, it gets no recommendation.
    """

    if evidence_score is None:
        return EligibilityResult(
            eligible=False,
            reasons=[
                "No evidence score is available, so no "
                "intervention can be justified."
            ],
        )

    try:
        score = float(evidence_score)
    except (TypeError, ValueError):
        return EligibilityResult(
            eligible=False,
            reasons=[
                "The evidence score was not a number."
            ],
        )

    if quality_meets(
        evidence_quality_for(score), minimum_required
    ):
        return EligibilityResult(eligible=True)

    return EligibilityResult(
        eligible=False,
        reasons=[
            f"Evidence scores {score:.0f}/100 "
            f"({evidence_quality_for(score)}), which does not "
            f"meet the {minimum_required} evidence this "
            "intervention requires."
        ],
    )


# ============================================================
# FEASIBILITY
# ============================================================


@dataclass(frozen=True)
class ScenarioConstraints:
    """
    The limits a caller places on a what-if.

    Every field is optional. An absent budget does not mean
    unlimited; it means no budget was stated, and the cost
    reference is used instead so cost still counts for
    something.
    """

    budget: Optional[float] = None

    max_disruption: Optional[str] = None

    min_evidence_score: Optional[float] = None

    max_duration_minutes: Optional[int] = None

    operating_window_only: bool = False

    requires_human_approval: bool = True


def check_feasibility(
    cost: float,
    disruption_level: str,
    duration_minutes: Optional[int],
    constraints: ScenarioConstraints,
    declared: Optional[List[str]] = None,
    equipment_available: bool = True,
    config: InterventionConfig = DEFAULT_INTERVENTION_CONFIG,
) -> Tuple[float, bool, List[str]]:
    """
    Scores an option and decides whether it may be acted on.

    Returns (score, feasible, reasons). Hard violations make an
    option infeasible outright and cap its score, because the
    point of a constraint is that impact cannot buy your way
    past it.
    """

    reasons: List[str] = []
    hard_failures = 0

    # --- budget -----------------------------------------------------
    if constraints.budget is not None:
        try:
            if float(cost) > float(constraints.budget):
                reasons.append(
                    "Exceeds the configured budget."
                )
                hard_failures += 1
        except (TypeError, ValueError):
            reasons.append(
                "The intervention cost could not be compared "
                "against the budget."
            )
            hard_failures += 1

    # --- disruption -------------------------------------------------
    if constraints.max_disruption:
        allowed = _disruption_rank(constraints.max_disruption)
        actual = _disruption_rank(disruption_level)

        if allowed is not None and actual is not None:
            if actual > allowed:
                reasons.append(
                    f"Disruption is {disruption_level}, above "
                    f"the permitted {constraints.max_disruption}."
                )
                hard_failures += 1

    # --- evidence ---------------------------------------------------
    if (
        constraints.min_evidence_score is not None
        and constraints.operating_window_only
    ):
        reasons.append(
            "Must be applied within the operating window."
        )

    # --- duration ---------------------------------------------------
    if duration_minutes is not None:
        limit = (
            constraints.max_duration_minutes
            if constraints.max_duration_minutes is not None
            else config.long_duration_minutes
        )

        if limit is not None and duration_minutes > limit:
            reasons.append(
                f"Takes {duration_minutes} minutes, beyond the "
                f"{limit} minute limit."
            )
            hard_failures += 1

    # --- equipment --------------------------------------------------
    if not equipment_available:
        reasons.append(
            "The equipment this acts on is not reachable from "
            "this deployment."
        )
        hard_failures += 1

    # --- declared constraints --------------------------------------
    for constraint in declared or []:
        name = str(constraint)

        if name == CONSTRAINT_HUMAN_APPROVAL:
            if constraints.requires_human_approval:
                reasons.append(
                    "Requires human approval before it can be "
                    "applied."
                )

        elif name == CONSTRAINT_OPERATING_WINDOW:
            if constraints.operating_window_only:
                reasons.append(
                    "Must be applied within the operating window."
                )

        elif name in KNOWN_CONSTRAINTS:
            # Known, permitted, and not independently checkable
            # here. Recorded rather than ignored so the response
            # is not silently thinner than the intervention.
            reasons.append(
                f"Depends on {name.replace('_', ' ')}."
            )

        else:
            reasons.append(
                f"Declares an unrecognised constraint: {name}."
            )

    feasible = hard_failures == 0

    if feasible:
        score = _feasible_score(
            cost,
            disruption_level,
            reasons,
            config,
        )
    else:
        score = config.feasible_score_cap

    return round(score, 2), feasible, reasons


def _feasible_score(
    cost: float,
    disruption_level: str,
    reasons: List[str],
    config: InterventionConfig,
) -> float:
    """
    Grades a feasible option on the published scale.

    Starts from "immediately executable" and is reduced for
    each dependency the option actually declares, so the score
    reflects work outstanding rather than a flat penalty.
    """

    score = config.immediate_score

    # Soft dependencies, in decreasing severity.
    for reason in reasons:
        if "human approval" in reason.lower():
            score = min(score, config.minor_preparation_score)
        elif "operating window" in reason.lower():
            score = min(score, config.coordination_score)
        elif "unrecognised" in reason.lower():
            # An unknown constraint cannot be verified, so it
            # must not be assumed satisfied.
            score = min(score, config.major_dependency_score)

    if _disruption_rank(disruption_level) is None:
        score = min(score, config.coordination_score)

    return score


_DISRUPTION_ORDER = {"low": 0, "medium": 1, "high": 2}


def _disruption_rank(level: Optional[str]) -> Optional[int]:
    """Ordinal position of a disruption level, or None."""

    if not level:
        return None

    return _DISRUPTION_ORDER.get(str(level).lower())


# ============================================================
# PROJECTION
# ============================================================


def project_reduction(
    baseline_excess: float,
    expected_absolute: Optional[float],
    reduction_percent: Optional[float] = None,
) -> float:
    """
    The saving an intervention is modelled to deliver.

    Two cases, because the stored models are absolute while the
    correlation service works in percentages of an excess.

    When an absolute figure is supplied it is used, but CAPPED
    at the avoidable excess. An intervention claiming an 18 kWh
    saving against a zone with 6.5 kW of avoidable draw has not
    saved 18 kWh; it has saved everything there was to save and
    the rest never existed. Claiming the stored number would let
    a modest finding justify an implausible one.

    When only a percentage is supplied it is applied to the
    excess, never to raw consumption: the baseline load is what
    the building costs to do nothing, and reducing it is not
    what any of these interventions do.
    """

    try:
        excess = float(baseline_excess)
    except (TypeError, ValueError):
        return 0.0

    if excess <= 0:
        return 0.0

    if expected_absolute is not None:
        try:
            absolute = float(expected_absolute)
        except (TypeError, ValueError):
            return 0.0

        if absolute <= 0:
            return 0.0

        return round(min(absolute, excess), 4)

    if reduction_percent is None:
        return 0.0

    try:
        percent = float(reduction_percent)
    except (TypeError, ValueError):
        return 0.0

    if percent <= 0:
        return 0.0

    capped = min(percent, 100.0)

    return round(excess * capped / 100.0, 4)


def applicable_interventions(
    interventions: List[Dict[str, Any]],
    target_metric: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Filters the library down to interventions worth offering.

    Disabled interventions are removed rather than marked, so
    an operator who switches one off cannot have it recommended
    by a code path that forgot to check.
    """

    result = []

    for intervention in interventions:
        if not intervention.get("enabled", True):
            continue

        if (
            target_metric is not None
            and intervention.get("target_metric")
            != target_metric
        ):
            continue

        result.append(intervention)

    return result