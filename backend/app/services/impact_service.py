"""
Impact service (Phase 9).

Turns a correlation finding plus an intervention's own stated
model into a projection and a score.

The important arithmetic happens in `project_reduction`: the
saving is a percentage of the EXCESS over baseline, never of
raw consumption. An empty zone drawing 8.5 kW against a 2.0 kW
baseline has 6.5 kW of avoidable draw; the baseline load is
what the building costs to do nothing, and reducing it is not
what any of these interventions do.

Every projected figure is returned with a provenance label.
Nothing here produces a `measured` value, because nothing here
measures anything.
"""

import logging
from typing import Any, Dict, Optional

from app.core.impact_rules import (
    BASELINE_MEASURED_CREDIT,
    DEFAULT_IMPACT_REFERENCES,
    DEFAULT_IMPACT_WEIGHTS,
    VALUE_MODELED,
    calculate_confidence_score,
    calculate_impact_score,
    stress_band,
)
from app.core.intervention_rules import project_reduction
from app.models.impact import ImpactAssessment, ProjectedImpact
from app.models.intervention import Intervention


logger = logging.getLogger(__name__)


def _num(value, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def baseline_excess(
    energy_kw: Optional[float],
    expected_energy_kw: Optional[float],
) -> float:
    """
    The avoidable draw for a zone.

    Zero when consumption is at or below baseline: there is no
    excess to reduce, and a negative excess would otherwise
    produce a negative "saving".
    """

    measured = _num(energy_kw)
    expected = _num(expected_energy_kw)

    return round(max(0.0, measured - expected), 4)


class ImpactService:
    """
    Projects and scores what an intervention would achieve.
    """

    def __init__(
        self,
        weights=DEFAULT_IMPACT_WEIGHTS,
        references=DEFAULT_IMPACT_REFERENCES,
    ):
        self.weights = weights
        self.references = references

    # ----------------------------------------------------------
    # Projection
    # ----------------------------------------------------------

    def project_energy(
        self,
        intervention: Intervention,
        excess_kw: float,
    ) -> ProjectedImpact:
        """
        Projects the energy saving for one intervention.

        The percentage comes from the intervention's own impact
        model. An intervention with no energy model projects
        nothing rather than a guess, because a zero here is
        meaningful: it says "this action does not address
        energy", not "we could not work it out".
        """

        model = intervention.impact_for("energy")

        expected_absolute = intervention.expected_for("energy")

        percent = model.reduction_percent if model else None

        if excess_kw <= 0 or (
            not expected_absolute and not percent
        ):
            # Zero here means "this action does not address
            # energy", not "we could not work it out".
            return ProjectedImpact(
                metric="energy",
                value=0.0,
                unit="kW",
                value_type=VALUE_MODELED,
                confidence=(
                    model.confidence if model else None
                ),
                worst_case=0.0,
                expected_case=0.0,
                best_case=0.0,
                band_available=False,
            )

        value = project_reduction(
            excess_kw, expected_absolute, percent
        )

        worst, expected, best = stress_band(
            value,
            minimum=model.minimum_value if model else None,
            maximum=model.maximum_value if model else None,
            baseline_percent=percent,
            max_percent=(
                model.max_reduction_percent if model else None
            ),
        )

        # The whole band is capped at the avoidable excess, not
        # just the point estimate. An intervention's stored best
        # case describes what it could achieve against a large
        # enough problem; against 1.4 kW of avoidable draw it
        # cannot deliver 8.2 kW however favourable the scenario,
        # and a band that says otherwise overstates the upside.
        worst = min(worst, excess_kw)
        expected = min(expected, excess_kw)
        best = min(best, excess_kw)

        # Capping can collapse the ordering, so re-assert it.
        worst = min(worst, expected)
        best = max(best, expected)

        band_available = bool(
            model
            and (
                model.minimum_value is not None
                or model.maximum_value is not None
                or (
                    model.reduction_percent is not None
                    and model.max_reduction_percent is not None
                )
            )
        )

        return ProjectedImpact(
            metric="energy",
            value=value,
            unit="kW",
            value_type=VALUE_MODELED,
            confidence=(
                model.confidence if model
                else intervention.confidence
            ),
            worst_case=worst,
            expected_case=expected,
            best_case=best,
            band_available=band_available,
        )

    def project_scalar(
        self,
        intervention: Intervention,
        metric: str,
        unit: str,
    ) -> ProjectedImpact:
        """
        Projects a non-energy resource.

        These are absolute figures from the intervention's own
        model rather than percentages of an excess, because
        there is no meaningful "excess water" reading to apply a
        percentage to.
        """

        model = intervention.impact_for(metric)

        stored = intervention.expected_for(metric)

        expected_value = (
            model.expected_value
            if model and model.expected_value is not None
            else stored
        )

        if expected_value is None:
            return ProjectedImpact(
                metric=metric,
                value=0.0,
                unit=unit,
                value_type=VALUE_MODELED,
                band_available=False,
            )

        worst, expected, best = stress_band(
            expected_value,
            minimum=model.minimum_value if model else None,
            maximum=model.maximum_value if model else None,
            baseline_percent=(
                model.reduction_percent if model else None
            ),
            max_percent=(
                model.max_reduction_percent if model else None
            ),
        )

        return ProjectedImpact(
            metric=metric,
            value=expected,
            unit=unit,
            value_type=VALUE_MODELED,
            confidence=(
                model.confidence if model
                else intervention.confidence
            ),
            worst_case=worst,
            expected_case=expected,
            best_case=best,
            band_available=bool(
                model
                and (
                    model.minimum_value is not None
                    or model.maximum_value is not None
                )
            ),
        )

    # ----------------------------------------------------------
    # Scoring
    # ----------------------------------------------------------

    def confidence_for(
        self,
        intervention: Intervention,
        context: Dict[str, Any],
    ) -> float:
        """
        Confidence in this specific decision.

        Drawn from four recorded things: how well the camera
        saw, whether telemetry was fresh, whether "normal" was
        measured rather than assumed, and how well this action
        is understood. Each is a different question, and an
        option backed by three good answers and one bad one
        should not outrank one backed by four.
        """

        observation = context.get("observation") or {}

        model = intervention.impact_for(
            intervention.target_metric
        )

        return calculate_confidence_score(
            vision_confidence=_num(
                observation.get("confidence"), 0.0
            ),
            telemetry_fresh=bool(
                context.get("telemetry_fresh")
            ),
            # A baseline derived from measured history earns
            # full credit; one derived from zone capacity is a
            # design assumption and cannot.
            baseline_measured=bool(
                context.get("baseline_measured")
            ),
            intervention_confidence=(
                model.confidence if model else None
            ),
        )

    def assess(
        self,
        intervention: Intervention,
        context: Dict[str, Any],
        energy_kw: Optional[float],
        expected_energy_kw: Optional[float],
        business_priority: float = 1.0,
    ) -> ImpactAssessment:
        """
        Full impact and confidence assessment for one option.
        """

        excess = baseline_excess(
            energy_kw, expected_energy_kw
        )

        energy = self.project_energy(intervention, excess)
        water = self.project_scalar(
            intervention, "water", "litres/day"
        )
        waste = self.project_scalar(
            intervention, "waste", "kg/week"
        )
        co2 = self.project_scalar(
            intervention, "co2", "kg/year"
        )

        impact = calculate_impact_score(
            energy_reduction=energy.value,
            water_reduction=water.value,
            waste_reduction=waste.value,
            co2_reduction=co2.value,
            business_priority=business_priority,
            weights=self.weights,
            references=self.references,
        )

        confidence = self.confidence_for(
            intervention, context
        )

        return ImpactAssessment(
            impact_score=impact,
            confidence_score=confidence,
            energy_reduction_kw=energy.value,
            water_reduction_litres=(
                water.value if water.value else None
            ),
            waste_reduction_kg=(
                waste.value if waste.value else None
            ),
            co2_reduction_kg=co2.value if co2.value else None,
            weights_used={
                "energy": self.weights.energy,
                "water": self.weights.water,
                "waste": self.weights.waste,
                "co2": self.weights.co2,
                "business_priority": (
                    self.weights.business_priority
                ),
            },
        )


impact_service = ImpactService()