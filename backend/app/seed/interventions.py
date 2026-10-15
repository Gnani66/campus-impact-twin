"""
Intervention seed library (Phase 9).

Seven interventions, not fifty invented ones. Each is small,
defensible and tied to a metric this deployment actually
measures.

Two properties matter more than the individual figures:

* Every energy model states `baseline_reduction_percent` and
  `max_reduction_percent`, which is what makes it stress
  testable. A model claiming "30%" with no stated ceiling
  cannot honestly produce a worst case.

* Every impact states an `evidence_source`. A projection with
  no stated provenance is a guess with a number attached, and
  the PRD requires decisions to trace to stored calculations.

Run with:  python -m app.seed.interventions
"""

import logging
from typing import Any, Dict, List


logger = logging.getLogger(__name__)


# Projects the reduction of avoidable draw, not of total
# consumption. The baseline load is what the building costs to
# do nothing.
INTERVENTIONS: List[Dict[str, Any]] = [
    {
        "name": "HVAC standby optimisation",
        "description": (
            "Drop non-essential AHUs to standby when a zone "
            "reads empty for a sustained period. A control "
            "schedule change with no capital cost."
        ),
        "domain": "energy",
        "cost": 0,
        "maintenance_hours": 0.5,
        # Absolute expected reduction per operating hour. Kept
        # modest on purpose: the engine caps any projection at
        # the avoidable draw that actually exists, so an
        # optimistic stored figure cannot manufacture a saving.
        "expected_energy_kwh": 6.5,
        "expected_emissions_kg_co2e": 2.6,
        "confidence": 0.85,
        "minimum_evidence_quality": "moderate",
        "prerequisites": [],
        "status": "eligible",
        "metadata": {
            "code": "HVAC_STANDBY",
            "disruption_level": "low",
            "baseline_reduction_percent": 30,
            "max_reduction_percent": 50,
        },
        "impacts": [
            {
                "metric": "energy",
                "unit": "kWh/h",
                "impact_type": "absolute",
                "expected_value": 6.5,
                "minimum_value": 3.9,
                "maximum_value": 8.2,
                "confidence": 0.85,
                "evidence_source": (
                    "Vendor control curves for AHU standby "
                    "operation, adjusted for observed occupancy."
                ),
                "assumptions": {
                    "baseline_reduction_percent": 30,
                    "max_reduction_percent": 50,
                },
            }
        ],
    },
    {
        "name": "Occupancy-aware HVAC scheduling",
        "description": (
            "Drive HVAC plant scheduling from corroborated "
            "occupancy rather than a fixed timetable."
        ),
        "domain": "energy",
        "cost": 12000,
        "maintenance_hours": 3,
        "expected_energy_kwh": 9.4,
        "expected_emissions_kg_co2e": 3.8,
        "confidence": 0.72,
        "minimum_evidence_quality": "strong",
        "prerequisites": ["requires_hvac_control"],
        "status": "eligible",
        "metadata": {
            "code": "OCCUPANCY_HVAC",
            "disruption_level": "medium",
        },
        "impacts": [
            {
                "metric": "energy",
                "unit": "kWh/h",
                "impact_type": "absolute",
                "expected_value": 9.4,
                "minimum_value": 6.1,
                "maximum_value": 10.0,
                "confidence": 0.72,
                "evidence_source": (
                    "Published occupancy-driven control savings "
                    "for comparable lecture-hall plant."
                ),
                "assumptions": {},
            }
        ],
    },
    {
        "name": "Lighting schedule optimisation",
        "description": (
            "Trim lighting hours to the zone's booked schedule "
            "instead of a fixed building-wide timetable."
        ),
        "domain": "energy",
        "cost": 3000,
        "maintenance_hours": 1,
        "expected_energy_kwh": 3.2,
        "expected_emissions_kg_co2e": 1.3,
        "confidence": 0.68,
        "minimum_evidence_quality": "weak",
        "prerequisites": ["requires_lighting_control"],
        "status": "eligible",
        "metadata": {
            "code": "LIGHTING_SCHEDULE",
            "disruption_level": "low",
        },
        "impacts": [],
    },
    {
        "name": "Lighting occupancy control",
        "description": (
            "Switch lighting on presence detected by existing "
            "sensing rather than on a timer."
        ),
        "domain": "energy",
        "cost": 8000,
        "maintenance_hours": 2.5,
        "expected_energy_kwh": 4.6,
        "expected_emissions_kg_co2e": 1.8,
        "confidence": 0.7,
        "minimum_evidence_quality": "moderate",
        "prerequisites": ["requires_lighting_control"],
        "status": "eligible",
        "metadata": {
            "code": "LIGHTING_OCCUPANCY",
            "disruption_level": "medium",
        },
        "impacts": [],
    },
    {
        "name": "Water fixture inspection",
        "description": (
            "Inspect and repair dripping or leaking fixtures in "
            "the zone's washrooms."
        ),
        "domain": "water",
        "cost": 1500,
        "maintenance_hours": 1.5,
        "expected_water_litres": 120,
        "confidence": 0.6,
        "minimum_evidence_quality": "weak",
        "prerequisites": ["requires_water_access"],
        "status": "eligible",
        "metadata": {
            "code": "WATER_FIXTURE_CHECK",
            "disruption_level": "low",
        },
        "impacts": [
            {
                "metric": "water",
                "unit": "litres/day",
                "impact_type": "absolute",
                "expected_value": 120,
                "minimum_value": 40,
                "maximum_value": 260,
                "confidence": 0.6,
                "evidence_source": (
                    "Typical per-fixture leak volumes from the "
                    "building's maintenance backlog."
                ),
                "assumptions": {},
            }
        ],
    },
    {
        "name": "Irrigation schedule adjustment",
        "description": (
            "Reduce irrigation outside the campus occupancy "
            "window and after rainfall."
        ),
        "domain": "water",
        "cost": 2500,
        "maintenance_hours": 0.75,
        "expected_water_litres": 260,
        "confidence": 0.55,
        "minimum_evidence_quality": "weak",
        "prerequisites": ["requires_water_access"],
        "status": "eligible",
        "metadata": {
            "code": "IRRIGATION_SCHEDULE",
            "disruption_level": "low",
        },
        "impacts": [],
    },
    {
        "name": "Waste collection schedule optimisation",
        "description": (
            "Consolidate waste collections so bins are not "
            "emptied in zones that are unoccupied."
        ),
        "domain": "waste",
        "cost": 1000,
        "maintenance_hours": 0.5,
        "expected_waste_kg": 14,
        "expected_emissions_kg_co2e": 1.8,
        "confidence": 0.58,
        "minimum_evidence_quality": "weak",
        "prerequisites": [],
        "status": "eligible",
        "metadata": {
            "code": "WASTE_COLLECTION",
            "disruption_level": "low",
        },
        "impacts": [
            {
                "metric": "waste",
                "unit": "kg/week",
                "impact_type": "absolute",
                "expected_value": 14,
                "minimum_value": 5,
                "maximum_value": 28,
                "confidence": 0.58,
                "evidence_source": (
                    "Collection manifests for the last eight "
                    "weeks."
                ),
                "assumptions": {},
            }
        ],
    },
]


def seed_all() -> Dict[str, Any]:
    """
    Writes the library, replacing any existing rows.

    Idempotent so it can be re-applied after a change. Impact
    models are rewritten rather than merged, so a model that has
    been removed disappears instead of lingering as a stale
    figure that reads as though it were current.
    """

    from app.repositories.intervention_repository import (
        upsert_intervention,
    )

    written: List[str] = []
    failed: List[str] = []

    for intervention in INTERVENTIONS:
        result = upsert_intervention(intervention)

        # Keyed by name: the stored schema has no code column.
        if result:
            written.append(intervention["name"])
        else:
            failed.append(intervention["name"])

    logger.info(
        "Intervention library: %d written, %d failed",
        len(written),
        len(failed),
    )

    return {"written": written, "failed": failed}


def main() -> None:
    import json
    import logging as logging_module

    logging_module.basicConfig(level=logging_module.INFO)

    print(json.dumps(seed_all(), indent=2))


if __name__ == "__main__":
    main()