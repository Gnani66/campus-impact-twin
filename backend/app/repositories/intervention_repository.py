"""
Intervention and impact repository.

All SQL for the Phase 9 library lives here, against the schema
that actually exists. That schema is PRD-derived and differs
from the Phase 9 sketch: interventions are keyed by `name`,
evidence quality is an enum rather than a score, expected
effects are absolute figures on the row, and availability is
expressed through the `status` enum rather than a boolean.

Every read degrades to an empty result rather than raising. A
missing library must leave the engine with nothing to offer,
which it reports as a refusal, not as a server fault.
"""

import logging
from typing import Any, Dict, List, Optional

from app.db.supabase import get_supabase
from app.models.intervention import (
    ImpactModel,
    Intervention,
)


logger = logging.getLogger(__name__)


INTERVENTIONS_TABLE = "interventions"
IMPACTS_TABLE = "intervention_impacts"

COLUMNS = (
    "id,name,domain,description,cost,maintenance_hours,"
    "expected_energy_kwh,expected_water_litres,"
    "expected_waste_kg,expected_emissions_kg_co2e,"
    "confidence,minimum_evidence_quality,prerequisites,"
    "incompatible_with,status,metadata"
)


def _impact_from_row(row: Dict[str, Any]) -> ImpactModel:
    return ImpactModel(
        metric=row.get("metric") or "",
        unit=row.get("unit") or "",
        impact_type=row.get("impact_type") or "absolute",
        expected_value=_num(row.get("expected_value")),
        minimum_value=_num(row.get("minimum_value")),
        maximum_value=_num(row.get("maximum_value")),
        confidence=_num(row.get("confidence")),
        evidence_source=row.get("evidence_source") or "",
        assumptions=(
            row.get("assumptions")
            if isinstance(row.get("assumptions"), dict)
            else {}
        ),
    )


def _num(
    value, default: Optional[float] = None
) -> Optional[float]:
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_impacts(
    intervention_ids: List[str],
) -> Dict[str, List[ImpactModel]]:
    """
    Detailed impact models for a set of interventions.

    Optional enrichment: the expectation figures live on the
    intervention row itself, so a failure here degrades the
    provenance detail without losing the numbers.
    """

    if not intervention_ids:
        return {}

    try:
        result = (
            get_supabase()
            .table(IMPACTS_TABLE)
            .select(
                "intervention_id,metric,unit,impact_type,"
                "expected_value,minimum_value,maximum_value,"
                "confidence,evidence_source,assumptions"
            )
            .in_("intervention_id", intervention_ids)
            .execute()
        )
    except Exception:
        logger.exception(
            "Failed to read detailed impact models"
        )

        return {}

    grouped: Dict[str, List[ImpactModel]] = {}

    for row in result.data or []:
        grouped.setdefault(
            str(row.get("intervention_id")), []
        ).append(_impact_from_row(row))

    return grouped


def list_interventions(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    names: Optional[List[str]] = None,
) -> List[Intervention]:
    """
    The intervention library.

    `status` is applied in storage rather than in Python so a
    retired intervention is never even loaded into the engine.
    Callers that need to show retired rows (an operator
    re-enabling one) pass no status.
    """

    try:
        query = get_supabase().table(INTERVENTIONS_TABLE).select(
            COLUMNS
        )

        if domain:
            query = query.eq("domain", domain)

        if status:
            query = query.eq("status", status)

        if names:
            query = query.in_("name", names)

        result = query.order("name").execute()
    except Exception:
        logger.exception(
            "Failed to read the intervention library"
        )

        return []

    rows = result.data or []

    if not rows:
        return []

    impacts = load_impacts(
        [str(row.get("id")) for row in rows if row.get("id")]
    )

    return [
        Intervention.from_row(
            row, impacts.get(str(row.get("id")), [])
        )
        for row in rows
    ]


def get_intervention(
    identifier: str,
) -> Optional[Intervention]:
    """
    One intervention by name or by stored code.

    The API addresses interventions by a readable code, which is
    derived from the name unless metadata carries one. Both are
    accepted so a client can use whichever it was given.
    """

    matches = list_interventions(names=[identifier])

    if matches:
        return matches[0]

    for intervention in list_interventions():
        if intervention.code == identifier:
            return intervention

    return None


def upsert_intervention(
    payload: Dict[str, Any],
) -> Optional[str]:
    """
    Writes one intervention, replacing its impact models.

    Idempotent so the library can be re-applied after a change.
    Models are rewritten rather than merged: a figure that has
    been withdrawn should disappear rather than linger as a
    stale number that reads as though it were current.
    """

    name = payload.get("name")

    if not name:
        return None

    impacts = payload.get("impacts") or []

    row = {
        "name": name,
        "domain": payload.get("domain", "energy"),
        "description": payload.get("description"),
        "cost": payload.get("cost", 0),
        "maintenance_hours": payload.get(
            "maintenance_hours", 0
        ),
        # The expectation columns are NOT NULL in the stored
        # schema, so a resource this intervention does not touch
        # is stored as 0 rather than null. Zero means "no effect
        # claimed", which is exactly right; a null would claim
        # the question was never asked.
        "expected_energy_kwh": _num(
            payload.get("expected_energy_kwh"), 0.0
        ),
        "expected_water_litres": _num(
            payload.get("expected_water_litres"), 0.0
        ),
        "expected_waste_kg": _num(
            payload.get("expected_waste_kg"), 0.0
        ),
        "expected_emissions_kg_co2e": _num(
            payload.get("expected_emissions_kg_co2e"), 0.0
        ),
        "confidence": payload.get("confidence"),
        "minimum_evidence_quality": payload.get(
            "minimum_evidence_quality", "moderate"
        ),
        "prerequisites": payload.get("prerequisites", []),
        "incompatible_with": payload.get(
            "incompatible_with", []
        ),
        "status": payload.get("status", "eligible"),
        "metadata": payload.get("metadata", {}),
    }

    try:
        existing = (
            get_supabase()
            .table(INTERVENTIONS_TABLE)
            .select("id")
            .eq("name", name)
            .limit(1)
            .execute()
        )

        found = existing.data or []

        if found:
            intervention_id = found[0]["id"]

            (
                get_supabase()
                .table(INTERVENTIONS_TABLE)
                .update(row)
                .eq("id", intervention_id)
                .execute()
            )
        else:
            inserted = (
                get_supabase()
                .table(INTERVENTIONS_TABLE)
                .insert(row)
                .execute()
                .data
            )

            intervention_id = (
                inserted[0]["id"] if inserted else None
            )

        if intervention_id is not None and impacts:
            (
                get_supabase()
                .table(IMPACTS_TABLE)
                .delete()
                .eq("intervention_id", intervention_id)
                .execute()
            )

            (
                get_supabase()
                .table(IMPACTS_TABLE)
                .insert(
                    [
                        {
                            "intervention_id": intervention_id,
                            "metric": impact.get("metric"),
                            "unit": impact.get("unit"),
                            "impact_type": impact.get(
                                "impact_type", "absolute"
                            ),
                            "expected_value": impact.get(
                                "expected_value"
                            ),
                            "minimum_value": impact.get(
                                "minimum_value"
                            ),
                            "maximum_value": impact.get(
                                "maximum_value"
                            ),
                            "confidence": impact.get(
                                "confidence"
                            ),
                            "evidence_source": impact.get(
                                "evidence_source", "seed library"
                            ),
                            "assumptions": impact.get(
                                "assumptions", {}
                            ),
                        }
                        for impact in impacts
                    ]
                )
                .execute()
            )

        return str(intervention_id)

    except Exception:
        logger.exception(
            "Failed to seed intervention '%s'", name
        )

        return None