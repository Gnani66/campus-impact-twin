"""
Domain models for Phase 9 interventions.

These map onto the schema that actually exists in the database,
which is not the shape the Phase 9 specification sketched. The
stored model is PRD-derived and differs in three ways that
matter:

* Interventions are identified by `name`. There is no `code`
  column, so `code` here is a slug of the name.
* Evidence quality is an enum (`weak` / `moderate` / `strong`),
  not a 0-100 score. The conversion lives in
  `app.core.intervention_rules` because it is a product
  judgement, not a storage concern.
* Expected effects are ABSOLUTE figures per resource
  (`expected_energy_kwh`, `expected_water_litres`, ...) rather
  than percentages of an excess.

The last point is the one that changes the arithmetic: a stored
"18 kWh saving" has to be reconciled against how much avoidable
draw actually exists right now, and the smaller of the two is
the honest projection.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Domains the stored enum is known to use. Kept as data rather
# than an enum so an unrecognised domain from a future row does
# not raise on import.
DOMAIN_ENERGY = "energy"
DOMAIN_WATER = "water"
DOMAIN_WASTE = "waste"


def slugify(value: str) -> str:
    """
    A machine-readable identifier for an intervention.

    The schema has no code column, so the API exposes a slug
    derived from the name. It is stable for a given name and
    readable, which is what a client needs to request one.
    """

    parts = [
        piece
        for piece in "".join(
            ch if ch.isalnum() else " " for ch in (value or "")
        ).split()
        if piece
    ]

    return "_".join(piece.upper() for piece in parts)


@dataclass(frozen=True)
class ImpactModel:
    """
    What one intervention is modelled to achieve on one metric.

    Mirrors the `intervention_impacts` table, which carries the
    reasoning behind a figure: its source, its bounds, and how
    certain it is. The same values also live on the intervention
    row for convenience; this type is the richer form.
    """

    metric: str

    unit: str

    impact_type: str = "absolute"

    expected_value: Optional[float] = None

    minimum_value: Optional[float] = None

    maximum_value: Optional[float] = None

    confidence: Optional[float] = None

    # Prose naming where the figure came from. Required rather
    # than optional: a figure whose provenance cannot be stated
    # is not one anyone should act on.
    evidence_source: str = ""

    assumptions: Dict[str, Any] = field(default_factory=dict)

    @property
    def reduction_percent(self) -> Optional[float]:
        """
        A percentage, when the model states one.

        The stored models are absolute, so this is usually
        None. It is read anyway because a percentage is the more
        transferable form when one exists.
        """

        return _optional_float(
            self.assumptions.get("baseline_reduction_percent")
        )

    @property
    def max_reduction_percent(self) -> Optional[float]:
        """The ceiling the model puts on itself, if any."""

        return _optional_float(
            self.assumptions.get("max_reduction_percent")
        )


@dataclass(frozen=True)
class Intervention:
    """
    A candidate action the system may offer.

    An intervention is a possibility with stated cost,
    maintenance burden, expected effects and an evidence bar.
    It is not an incident and not a decision.
    """

    id: Optional[str]

    name: str

    # The stored enum: energy / water / waste / ...
    domain: str

    description: Optional[str] = None

    cost: float = 0.0

    maintenance_hours: float = 0.0

    # Absolute expected effects per resource. Stored figures are
    # per operating period; the phase treats them as kWh per hour
    # so they are commensurable with the instantaneous kW the
    # telemetry reports.
    expected_energy_kwh: Optional[float] = None

    expected_water_litres: Optional[float] = None

    expected_waste_kg: Optional[float] = None

    expected_emissions_kg_co2e: Optional[float] = None

    confidence: Optional[float] = None

    # Enum: weak / moderate / strong.
    minimum_evidence_quality: str = "moderate"

    prerequisites: List[str] = field(default_factory=list)

    incompatible_with: List[str] = field(default_factory=list)

    # Enum: eligible / disabled / ...
    status: str = "eligible"

    metadata: Dict[str, Any] = field(default_factory=dict)

    impacts: List[ImpactModel] = field(default_factory=list)

    # ---------------------------------------------------------
    # Derived
    # ---------------------------------------------------------

    @property
    def code(self) -> str:
        """Machine identifier, from the slug or the metadata."""

        stored = self.metadata.get("code")

        if stored:
            return str(stored)

        return slugify(self.name)

    @property
    def enabled(self) -> bool:
        """
        Whether the operator may offer this at all.

        Derived from the status enum. A retired or rejected
        intervention is not merely scored lower, it is removed,
        so no code path can recommend it by forgetting a check.
        """

        return str(self.status).lower() == "eligible"

    @property
    def disruption_level(self) -> str:
        """
        Operational disruption, from metadata or inferred.

        The schema has no disruption column. Seeded rows carry it
        in metadata; rows that predate Phase 9 are graded on
        maintenance hours, which is the closest proxy the stored
        data offers and is honest about being a proxy.
        """

        stored = self.metadata.get("disruption_level")

        if stored:
            return str(stored)

        hours = self.maintenance_hours or 0.0

        if hours <= 1:
            return "low"

        if hours <= 3:
            return "medium"

        return "high"

    @property
    def duration_minutes(self) -> int:
        """Maintenance burden expressed in minutes."""

        return int(round((self.maintenance_hours or 0.0) * 60))

    @property
    def target_metric(self) -> str:
        """
        The resource this intervention acts on.

        Inferred from which expected figure is populated, which
        is more reliable than the domain: a water intervention
        can also save a little energy.
        """

        if self.expected_water_litres:
            return "water"

        if self.expected_waste_kg:
            return "waste"

        return "energy"

    def expected_for(
        self, metric: str
    ) -> Optional[float]:
        """The stored absolute expectation for one metric."""

        return {
            "energy": self.expected_energy_kwh,
            "water": self.expected_water_litres,
            "waste": self.expected_waste_kg,
            "co2": self.expected_emissions_kg_co2e,
        }.get(metric)

    def impact_for(
        self, metric: str
    ) -> Optional[ImpactModel]:
        """The detailed model for a metric, if one is stored."""

        for model in self.impacts:
            if model.metric == metric:
                return model

        return None

    @classmethod
    def from_row(
        cls,
        row: Dict[str, Any],
        impacts: Optional[List[ImpactModel]] = None,
    ) -> "Intervention":
        """Builds an intervention from its stored columns."""

        return cls(
            id=row.get("id"),
            name=row.get("name") or "",
            domain=row.get("domain") or DOMAIN_ENERGY,
            description=row.get("description"),
            cost=_optional_float(row.get("cost"), 0.0),
            maintenance_hours=_optional_float(
                row.get("maintenance_hours"), 0.0
            ),
            expected_energy_kwh=_optional_float(
                row.get("expected_energy_kwh")
            ),
            expected_water_litres=_optional_float(
                row.get("expected_water_litres")
            ),
            expected_waste_kg=_optional_float(
                row.get("expected_waste_kg")
            ),
            expected_emissions_kg_co2e=_optional_float(
                row.get("expected_emissions_kg_co2e")
            ),
            confidence=_optional_float(row.get("confidence")),
            minimum_evidence_quality=(
                row.get("minimum_evidence_quality")
                or "moderate"
            ),
            prerequisites=_as_list(row.get("prerequisites")),
            incompatible_with=_as_list(
                row.get("incompatible_with")
            ),
            status=row.get("status") or "eligible",
            metadata=(
                row.get("metadata")
                if isinstance(row.get("metadata"), dict)
                else {}
            ),
            impacts=list(impacts or []),
        )


def _optional_float(
    value, default: Optional[float] = None
) -> Optional[float]:
    if value is None:
        return default

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    if number != number:  # NaN
        return default

    return number


def _as_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]

    return []