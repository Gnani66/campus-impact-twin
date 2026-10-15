"""
Domain models for Phase 9 impact projections.

A projection states what an intervention would achieve *and*
where that figure came from. The second half is not optional:
the PRD requires modelled outcomes to be labelled as modelled,
and a number without that label will eventually be rendered as
"You will save 2.1 kW" by a well-meaning interface.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProjectedImpact:
    """
    One resource projection, with its provenance and its band.
    """

    metric: str

    value: float

    unit: str

    # Always one of measured / modeled / estimated / simulated.
    # A projection produced by the decision engine is `simulated`;
    # one derived from an intervention's stated model is
    # `modeled`. Neither is ever `measured`.
    value_type: str

    confidence: Optional[float] = None

    worst_case: Optional[float] = None

    expected_case: Optional[float] = None

    best_case: Optional[float] = None

    # False when the model supplied no basis for a spread. A
    # zero-width band is not certainty, it is an absence of
    # information, and the caller must be able to tell the
    # difference.
    band_available: bool = True

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "value_type": self.value_type,
            "confidence": self.confidence,
            "worst_case": self.worst_case,
            "expected_case": self.expected_case,
            "best_case": self.best_case,
            "band_available": self.band_available,
        }


@dataclass(frozen=True)
class ImpactAssessment:
    """
    The impact and confidence figures for one option.
    """

    impact_score: float

    confidence_score: float

    energy_reduction_kw: Optional[float] = None

    water_reduction_litres: Optional[float] = None

    waste_reduction_kg: Optional[float] = None

    co2_reduction_kg: Optional[float] = None

    # The scoring weights actually used, so a stored result can
    # be re-scored later under different assumptions.
    weights_used: Optional[dict] = None