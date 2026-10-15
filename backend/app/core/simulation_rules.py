"""
Simulation rules (Phase 10).

The what-if engine. Given a zone's measured condition and a set
of candidate interventions, it scores each option, refuses the
ones that violate constraints, stress-tests the rest and ranks
what survives.

Ranking is deterministic down to the last tiebreaker. Two
options that score identically are separated by confidence,
then cost, then disruption, then impact, and finally by
intervention code. That last step exists so the ordering is a
total order: without it the sort is not deterministic and the
same query could return a different winner tomorrow, which
would undermine the entire audit trail.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ============================================================
# OUTCOMES
# ============================================================

# A simulation always ends in one of these. `no_safe_recommendation`
# and `blocked` are first-class outcomes, not failures: the
# engine saying "I will not recommend anything" is the correct
# result when the evidence does not support one.
STATUS_COMPLETED = "completed"
STATUS_BLOCKED = "blocked"
STATUS_NO_SAFE_RECOMMENDATION = "no_safe_recommendation"


@dataclass(frozen=True)
class Recommendation:
    """
    The engine's preferred option, or an explicit refusal.
    """

    intervention_code: Optional[str]

    overall_score: Optional[float]

    reason: str

    # Present even when nothing is recommended, so the caller can
    # explain the refusal without a second lookup.
    status: str = STATUS_COMPLETED


def rank_options(options: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Orders scored options, best first.

    Infeasible options sort last regardless of score. Their
    score is capped by the feasibility rules, but relying on
    that cap alone would be fragile, and an infeasible option
    appearing at the top of a recommendation list would be
    indefensible.
    """

    def key(option: Dict[str, Any]):
        return (
            not option.get("feasible", False),
            -_f(option.get("overall_score")),
            -_f(option.get("confidence_score")),
            _f(option.get("estimated_cost")),
            _disruption_rank(option.get("disruption_level")),
            -_f(option.get("impact_score")),
            str(option.get("code") or ""),
        )

    return sorted(options, key=key)


_DISRUPTION_ORDER = {"low": 0, "medium": 1, "high": 2}


def _disruption_rank(level: Optional[str]) -> int:
    """
    Ordinal for sorting.

    An unrecognised level sorts as maximally disruptive. Sorting
    it optimistically would let a malformed library entry beat
    every legitimate option on tie-breaks alone.
    """

    if not level:
        return 3

    return _DISRUPTION_ORDER.get(
        str(level).lower(), 3
    )


def _f(value) -> float:
    if value is None:
        return 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_recommendation(
    options: Sequence[Dict[str, Any]],
    status: str = STATUS_COMPLETED,
) -> Recommendation:
    """
    Chooses an option, or explains why none is offered.

    The refusal path is the important one. An engine that always
    produces a recommendation is a dashboard with extra steps;
    the ability to decline is what makes the recommendations it
    does make worth reading.
    """

    feasible = [
        option
        for option in options
        if option.get("feasible", False)
    ]

    if not feasible:
        if not options:
            return Recommendation(
                intervention_code=None,
                overall_score=None,
                reason=(
                    "No interventions were supplied to compare."
                ),
                status=STATUS_BLOCKED,
            )

        return Recommendation(
            intervention_code=None,
            overall_score=None,
            reason=(
                f"All {len(options)} option(s) violated at "
                "least one constraint, so none is safe to "
                "recommend."
            ),
            status=STATUS_NO_SAFE_RECOMMENDATION,
        )

    ranked = rank_options(feasible)

    best = ranked[0]

    return Recommendation(
        intervention_code=best.get("code"),
        overall_score=_f(best.get("overall_score")) or None,
        reason=_explain(best, ranked),
        status=status,
    )


def _explain(
    best: Dict[str, Any],
    ranked: List[Dict[str, Any]],
) -> str:
    """
    States the trade-off rather than just naming a winner.

    A recommendation with no stated trade-off is an instruction,
    not decision support. When a runner-up exists the reason
    names what was given up.
    """

    parts: List[str] = [
        f"Highest overall score at "
        f"{_f(best.get('overall_score')):.1f}"
    ]

    cost = _f(best.get("estimated_cost"))

    if cost <= 0:
        parts.append("no capital cost")

    disruption = best.get("disruption_level")

    if disruption:
        parts.append(f"{disruption} operational disruption")

    confidence = best.get("confidence_score")

    if confidence is not None:
        parts.append(f"{_f(confidence):.0f}% confidence")

    reason = ", ".join(parts) + "."

    if len(ranked) > 1:
        runner_up = ranked[1]

        reason += (
            f" Trade-off: {runner_up.get('code')} scored "
            f"{_f(runner_up.get('overall_score')):.1f} and "
            f"projects "
            f"{_f(runner_up.get('projected_energy_reduction')):.2f}"
            f" kW against "
            f"{_f(best.get('projected_energy_reduction')):.2f}"
            " kW here."
        )

    return reason


def comparison_summary(
    options: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    The trade-off picture, in the shape the API returns.

    Feasible and infeasible options are counted separately so a
    reader can see at a glance that a shortlist exists but was
    narrowed by constraints rather than by scoring.
    """

    feasible = [
        option
        for option in options
        if option.get("feasible", False)
    ]
    infeasible = [
        option
        for option in options
        if not option.get("feasible", False)
    ]

    return {
        "total": len(options),
        "feasible": len(feasible),
        "infeasible": len(infeasible),
        "best_option": (
            max(
                feasible,
                key=lambda option: _f(
                    option.get("overall_score")
                ),
            ).get("code")
            if feasible
            else None
        ),
        "rejected_codes": [
            option.get("code") for option in infeasible
        ],
    }


def validate_request(
    intervention_codes: Sequence[str],
    known_codes: Sequence[str],
) -> List[str]:
    """
    Returns the codes that do not exist.

    Reported rather than raised so the caller learns every
    mistake at once. Fixing them one request at a time is a
    waste of everyone's afternoon.
    """

    known = set(known_codes or [])

    return [
        code
        for code in (intervention_codes or [])
        if code not in known
    ]


def evidence_gate_reason(
    evidence_score: Optional[float],
    required: Optional[float],
) -> Optional[str]:
    """
    Why a simulation cannot proceed at all, or None.

    Distinct from per-option eligibility: this is about whether
    there is anything to reason from, not about one candidate.
    """

    if evidence_score is None:
        return (
            "No correlation run with an evidence score was "
            "found for this zone."
        )

    if required is not None and _f(evidence_score) < _f(required):
        return (
            f"Evidence score {_f(evidence_score):.0f} is below "
            f"the {_f(required):.0f} required to simulate."
        )

    return None