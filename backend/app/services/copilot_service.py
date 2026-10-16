"""
Copilot service (Phase 13).

Orchestrates: classify the intent, retrieve real campus state,
compute the deterministic analysis, then let the local model
phrase an explanation of what the backend already determined.

THE ANSWER IS NEVER THE MODEL'S TO SUPPLY.

Every response carries an `evidence` array and a
`recommendations` array, both computed in Python from stored
readings. The model produces only `answer`, the prose. If the
model hallucinates a temperature, it hallucinates it in a
sentence while the evidence array beside it still shows the real
value.

And every intent has a complete deterministic answer path. If
the local model is unreachable the copilot still answers every
question correctly, because the composed answer is built from the
same facts the model was given. The model upgrades wording; it
never supplies the answer.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from app.ai import llm
from app.ai.copilot import (
    INTENT_ENTITY_ANALYSIS,
    INTENT_EXPLANATION,
    INTENT_INCIDENT_ANALYSIS,
    INTENT_OVERVIEW,
    INTENT_RECOMMENDATION,
    INTENT_UNKNOWN,
    INTENT_WHAT_IF,
    build_entity_context,
    build_overview_context,
    classify_intent,
    summarise_issues,
)
from app.ai.prompts import (
    RECOMMENDATION_RULES,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.ai.schemas import (
    CopilotRecommendation,
    CopilotResponse,
    Evidence,
)
from app.services import campus_analysis


logger = logging.getLogger(__name__)


# ============================================================
# EVIDENCE
# ============================================================


def _entity_evidence(
    entity: Dict[str, Any],
) -> List[Evidence]:
    """
    Verified readings for one entity.

    Built from the same fields the twin panel renders, so the two
    surfaces cannot disagree.
    """

    evidence = [
        Evidence(
            source="twin_status",
            value=str(entity.get("status")),
            explanation=(
                "Status assigned by the backend from stored "
                "readings, not by the language model."
            ),
        )
    ]

    metrics = entity.get("metrics") or {}

    units = {
        "temperature": "C",
        "humidity": "%",
        "eco2": "ppm",
        "energy": "kW",
    }

    for key, unit in units.items():
        value = metrics.get(key)

        if value is None:
            evidence.append(
                Evidence(
                    source=f"telemetry.{key}",
                    value="not measured",
                    explanation=(
                        "This deployment has no sensor for this "
                        "measurement."
                    ),
                )
            )
            continue

        number = (
            f"{value:.0f}"
            if float(value).is_integer()
            else f"{value:.2f}"
        )

        evidence.append(
            Evidence(
                source=f"telemetry.{key}",
                value=f"{number} {unit}",
                explanation=(
                    "Most recent reading stored for this zone."
                ),
            )
        )

    # Declared explicitly when absent, because these appear in
    # operational questions and a reader who sees an AQI omitted
    # will assume the air is fine rather than that nothing knows.
    for key, label in (
        ("aqi", "Air quality index"),
        ("sound", "Sound level"),
    ):
        if metrics.get(key) is None:
            evidence.append(
                Evidence(
                    source=f"telemetry.{key}",
                    value="not measured",
                    explanation=(
                        f"{label}: this deployment has no "
                        "sensor for it."
                    ),
                )
            )

    occupancy = metrics.get("occupancy")

    evidence.append(
        Evidence(
            source="telemetry.occupancy",
            value=(
                "not measured"
                if occupancy is None
                else f"{int(occupancy)} people"
            ),
            explanation=(
                "Headcount from the occupancy sensor."
            ),
        )
    )

    ratio = metrics.get("occupancy_ratio")

    evidence.append(
        Evidence(
            source="telemetry.occupancy_ratio",
            value=(
                "unknown"
                if ratio is None
                else f"{round(float(ratio) * 100)}% of capacity"
            ),
            explanation=(
                "Occupancy relative to the zone's rated "
                "capacity."
            ),
        )
    )

    for reason in entity.get("reasons") or []:
        evidence.append(
            Evidence(
                source="threshold_evaluation",
                value="exceeded",
                explanation=reason,
            )
        )

    # Collapsed by kind, because four separate "open" rows that
    # read identically look like four separate problems and get
    # counted as four. The count is stated instead of implied.
    for text, count in summarise_issues(
        entity.get("active_issues") or []
    ):
        evidence.append(
            Evidence(
                source="incident_engine",
                value=f"{count} open",
                explanation=text,
            )
        )

    root_cause = entity.get("root_cause")

    if root_cause:
        evidence.append(
            Evidence(
                source="correlation_engine",
                value=str(entity.get("correlation_status")),
                explanation=str(root_cause),
            )
        )

    observed = entity.get("observed_at")

    if observed:
        evidence.append(
            Evidence(
                source="data_freshness",
                value=str(observed),
                explanation=(
                    "Timestamp of the readings above, UTC."
                ),
            )
        )

    return evidence


# ============================================================
# RECOMMENDATIONS
# ============================================================


def _recommendations_for(
    entity: Dict[str, Any],
) -> List[CopilotRecommendation]:
    """
    Suggestions drawn from a condition the backend detected.

    Each one cites a reading that actually caused it and is
    marked as requiring approval. They are advice about what a
    person might do, not instructions the system can carry out:
    nothing here reaches equipment.
    """

    status = str(entity.get("status") or "").lower()

    metrics = entity.get("metrics") or {}

    out: List[CopilotRecommendation] = []

    def add(action, rationale, effect):
        out.append(
            CopilotRecommendation(
                action=action,
                rationale=rationale,
                expected_effect=effect,
                requires_approval=True,
                entity_id=entity.get("id"),
                entity_name=entity.get("name"),
            )
        )

    # Overcrowding is the condition that most directly affects
    # people, so it is offered first and framed around occupancy
    # rather than around a number.
    ratio = metrics.get("occupancy_ratio")

    if ratio is not None and float(ratio) >= 1.0:
        add(
            "Review room allocation for the next scheduled "
            "session.",
            f"Occupancy is "
            f"{round(float(ratio) * 100)}% of the rated "
            f"capacity, with {int(metrics.get('occupancy') or 0)} "
            "people present.",
            "Reduce crowding and bring occupancy inside the "
            "zone's rated capacity.",
        )

    temperature = metrics.get("temperature")

    if (
        status in ("critical", "warning")
        and temperature is not None
        and float(temperature) >= 27.0
    ):
        add(
            "Increase ventilation and review the HVAC setpoint "
            "for this zone.",
            f"Temperature is {temperature:.1f} C, above the "
            "27.0 C warning threshold set for this campus.",
            "Bring temperature back inside the comfort band.",
        )

    co2 = metrics.get("eco2")

    if (
        status in ("critical", "warning")
        and co2 is not None
        and float(co2) >= 1000.0
    ):
        add(
            "Investigate ventilation in this zone.",
            f"CO2 is {co2:.0f} ppm, above the 1000 ppm warning "
            "threshold, which indicates ventilation is not "
            "keeping pace with occupancy.",
            "Reduce CO2 and improve perceived air quality.",
        )

    energy = metrics.get("energy")
    expected = (entity.get("root_cause") or "").lower()

    if (
        status in ("critical", "warning")
        and energy is not None
        and "energy" in expected
    ):
        add(
            "Review HVAC standby scheduling for this zone.",
            f"The correlation engine flagged this zone while "
            f"drawing {energy:.2f} kW.",
            "Reduce avoidable energy draw outside occupied "
            "hours.",
        )

    if status == "offline":
        add(
            "Check the telemetry feed for this zone.",
            "No live readings are arriving, so its current "
            "condition is unknown.",
            "Restore visibility of the zone before drawing any "
            "conclusion about it.",
        )

    return out


# ============================================================
# DETERMINISTIC ANSWERS
# ============================================================


def _overview_answer(snapshot: Dict[str, Any]) -> str:
    """
    A campus overview composed entirely from computed facts.

    This is what the copilot returns when the model is
    unavailable, and it is written so that it would be an entirely
    acceptable answer on its own.
    """

    counts = snapshot.get("counts") or {}

    critical = counts.get("critical", 0)
    warning = counts.get("warning", 0)
    offline = counts.get("offline", 0)

    total = snapshot.get("total_entities", 0)

    if total == 0:
        return (
            "No campus entities are configured, so there is "
            "nothing to report."
        )

    ranked = snapshot.get("ranked_entities") or []

    needing = [
        row for row in ranked if row.get("priority", 0) > 0
    ]

    lines = []

    if critical:
        lines.append(
            f"{critical} entity/entities are in a critical state."
        )
    elif warning:
        lines.append(
            f"{warning} entity/entities need attention."
        )
    else:
        lines.append(
            "No entity is currently outside its operational "
            "thresholds."
        )

    if offline:
        lines.append(
            f"{offline} entity/entities have stopped reporting."
        )

    if not needing:
        lines.append(
            "All measured readings are within their configured "
            "limits."
        )

        return "\n\n".join(lines)

    lines.append("")

    for index, row in enumerate(needing[:5], start=1):
        metrics = row.get("metrics") or {}

        header = (
            f"{index}. {row.get('name')} ({row.get('code')}) "
            f"- {str(row.get('status')).upper()}"
        )

        facts = []

        if temperature := metrics.get("temperature"):
            facts.append(f"Temperature {temperature:.1f} C")

        if ratio := metrics.get("occupancy_ratio"):
            facts.append(
                f"Occupancy {round(float(ratio) * 100)}% of "
                f"capacity"
            )

        if occupancy := metrics.get("occupancy"):
            facts.append(f"{int(occupancy)} people affected")

        if energy := metrics.get("energy"):
            facts.append(f"Energy {energy:.2f} kW")

        lines.append(header)

        if facts:
            lines.append("   " + ", ".join(facts))

        for reason in (row.get("reasons") or [])[:2]:
            lines.append(f"   {reason}")

        lines.append("")

    top = snapshot.get("top_priority") or {}

    if top:
        lines.append(
            f"Highest operational priority: {top.get('name')} "
            f"(priority {top.get('priority')}, ranked on "
            f"{int(top.get('people_affected') or 0)} people "
            "affected)."
        )

    return "\n".join(lines).strip()


def _entity_answer(entity: Dict[str, Any]) -> str:
    """
    Why an entity holds the status it does.
    """

    metrics = entity.get("metrics") or {}

    status = str(entity.get("status") or "").upper()

    lines = [
        f"{entity.get('name')} ({entity.get('code')}) is "
        f"classified {status.lower()} by the backend."
    ]

    reasons = entity.get("reasons") or []

    if reasons:
        lines.extend(["", "The backend assigned that status because:"])

        lines.extend(f"- {reason}" for reason in reasons)

        lines.append(
            ""
            "These are measured readings compared against the "
            "campus thresholds configured in the backend. The "
            "status was computed before any language model was "
            "involved."
        )

    else:
        lines.extend(
            [
                "",
                "No reading currently exceeds its threshold, so "
                "the zone is within its configured limits.",
            ]
        )

    missing = [
        key
        for key in (
            "temperature",
            "humidity",
            "eco2",
            "energy",
        )
        if metrics.get(key) is None
    ]

    if missing:
        lines.append(
            f"Not measured: {', '.join(missing)}. Those are "
            "absent sensors, not good readings."
        )

    observed = entity.get("observed_at")

    if observed:
        lines.append(f"Data timestamp (UTC): {observed}")

    return "\n".join(lines).strip()


def _recommendation_answer(
    entity: Optional[Dict[str, Any]],
    snapshot: Dict[str, Any],
) -> str:
    """
    Suggested next steps, each tied to a reading.
    """

    target = entity

    if target is None:
        ranked = snapshot.get("ranked_entities") or []

        target = snapshot.get("top_priority") or (
            ranked[0] if ranked else None
        )

    if target is None:
        return (
            "No entity currently has a detected condition, so "
            "there is nothing to recommend acting on."
        )

    suggestions = _recommendations_for(target)

    if not suggestions:
        return (
            f"{target.get('name')} is within its configured "
            "thresholds, so no intervention is indicated by the "
            "current evidence."
        )

    lines = [
        f"Suggested actions for {target.get('name')} "
        f"({target.get('code')}):",
        "",
    ]

    for index, suggestion in enumerate(suggestions, start=1):
        lines.append(f"{index}. {suggestion.action}")
        lines.append(f"   Reason: {suggestion.rationale}")
        lines.append(
            f"   Expected effect: {suggestion.expected_effect}"
        )
        lines.append(
            "   Human approval is required before any action "
            "is applied."
        )
        lines.append("")

    lines.append(
        "These are suggestions only. Nothing has been changed, "
        "and nothing will be without a person approving it."
    )

    return "\n".join(lines).strip()


def _what_if_answer(
    entity: Optional[Dict[str, Any]],
) -> str:
    """
    What-if questions are answered by the simulation engine,
    never by the model.
    """

    if entity is None:
        return (
            "A what-if needs a specific zone to model. Select an "
            "entity and ask again, or use the simulation endpoint "
            "directly, which compares interventions and their "
            "projected effects on the backend."
        )

    return (
        f"Modelling alternatives for {entity.get('name')} "
        f"({entity.get('code')}) is handled by the simulation "
        "engine, not by this copilot. That engine compares "
        "interventions on cost, impact, feasibility and "
        "constraint compliance, and returns a ranked shortlist "
        "with a modelled, not measured, projection. Ask for a "
        "recommendation instead, or open the simulation view for "
        "this zone."
    )


def _unknown_answer() -> str:
    return (
        "I did not recognise that request. I can report what "
        "needs attention across the campus, explain why a "
        "specific zone holds its current status, or suggest what "
        "might be done about a detected condition."
    )


# ============================================================
# ORCHESTRATION
# ============================================================


async def process_message(
    message: str,
    twin_snapshot: Dict[str, Any],
    entity: Optional[Dict[str, Any]] = None,
) -> CopilotResponse:
    """
    Answers a question from verified campus state.

    `twin_snapshot` and `entity` are injected rather than fetched
    here, which keeps this function testable and means the
    copilot cannot read anything the twin has not already
    judged.
    """

    intent = classify_intent(message, entity_id=(entity or {}).get("id"))

    snapshot = campus_analysis.build_snapshot(twin_snapshot)

    if entity is not None:
        snapshot = dict(snapshot)

        # Priority is computed campus-wide so a single-entity
        # number means the same thing as it would in an overview.
        worst = max(
            (
                campus_analysis.people_affected(row)
                for row in (snapshot.get("entities") or [entity])
            ),
            default=0.0,
        )

        entity = campus_analysis.entity_brief(entity, worst)

    if intent == INTENT_OVERVIEW:
        context = build_overview_context(snapshot)
        deterministic = _overview_answer(snapshot)

    elif intent in (INTENT_EXPLANATION, INTENT_ENTITY_ANALYSIS):
        if entity is None:
            top = snapshot.get("top_priority")

            if top is not None:
                entity = top

        if entity is None:
            deterministic = (
                "No campus entity is available to explain."
            )
        else:
            context = build_entity_context(entity)
            deterministic = _entity_answer(entity)

    elif intent in (INTENT_RECOMMENDATION, INTENT_INCIDENT_ANALYSIS):
        target = entity or snapshot.get("top_priority")

        # When the operator asks campus-wide what to do, the
        # copilot answers about one specific zone, so the response
        # carries that zone's readings as evidence. Returning a
        # campus-wide evidence list beside advice about one room
        # would leave the advice unverifiable.
        if entity is None and target is not None:
            entity = target

        context = (
            build_entity_context(target) if target else ""
        )
        deterministic = _recommendation_answer(target, snapshot)

    elif intent == INTENT_WHAT_IF:
        context = (
            build_entity_context(entity) if entity else ""
        )
        deterministic = _what_if_answer(entity)

    else:
        context = ""
        deterministic = _unknown_answer()

    system = SYSTEM_PROMPT

    if intent == INTENT_RECOMMENDATION:
        system = f"{SYSTEM_PROMPT}{RECOMMENDATION_RULES}"

    generated = await llm.generate(
        system_prompt=system,
        user_prompt=build_user_prompt(
            question=message,
            context=context,
            intent=intent,
        ),
    )

    # Evidence and recommendations are ALWAYS the deterministic
    # ones, whether or not the model answered.
    if entity is not None:
        evidence = _entity_evidence(entity)
        recommendations = _recommendations_for(entity)
    else:
        evidence = _overview_evidence(snapshot)
        recommendations = []

        for row in (
            snapshot.get("ranked_entities") or []
        )[:3]:
            recommendations.extend(_recommendations_for(row))

    caveats = list(snapshot.get("caveats") or [])

    # The status the backend actually assigned, which the prose is
    # not allowed to disagree with.
    verified_status = (
        str((entity or {}).get("status") or "").lower()
        if entity is not None
        else None
    )

    answer = deterministic
    source = "deterministic"

    if generated is not None:
        if contradicts_verified_status(
            generated, verified_status
        ):
            # The model described a severity the record does not
            # support. Its answer is dropped rather than corrected:
            # editing a hallucination produces a sentence nobody
            # verified, and the caveat below says plainly what
            # happened.
            caveats.append(
                "The generated narrative described a status that "
                "does not match the stored record, so it was "
                "discarded and this answer was composed directly "
                "from the readings."
            )
        else:
            # The footer is appended to the model's prose rather
            # than trusted in place of it, so the model still
            # narrates and the record is still printed on the same
            # screen.
            answer = (
                f"{generated.strip()}\n\n"
                f"{_verified_footer(entity, snapshot)}"
            )
            source = "llm"
    else:
        caveats.append(
            "The local language model was unavailable, so this "
            "answer was composed directly from stored readings."
        )

    return CopilotResponse(
        answer=answer,
        intent=intent,
        evidence=evidence,
        recommendations=recommendations,
        source=source,
        llm_available=generated is not None,
        entity_id=(entity or {}).get("id"),
        entity_name=(entity or {}).get("name"),
        priority=(entity or {}).get("priority"),
        caveats=caveats,
        context=snapshot,
    )


def _overview_evidence(
    snapshot: Dict[str, Any],
) -> List[Evidence]:
    """
    Campus-wide evidence.

    The counts, then the full reading set for the two most
    operationally significant entities. A per-entity summary line
    would be shorter, but it packs eight readings into one string
    that nobody can check; the same evidence the scoped view
    returns is used here so both paths can be read the same way.
    """

    counts = snapshot.get("counts") or {}

    evidence = [
        Evidence(
            source="campus_counts",
            value=(
                f"{counts.get('critical', 0)} critical, "
                f"{counts.get('warning', 0)} warning, "
                f"{counts.get('offline', 0)} offline, out of "
                f"{snapshot.get('total_entities', 0)} entities"
            ),
            explanation=(
                "Counted by the backend from stored readings."
            ),
        )
    ]

    for row in (snapshot.get("ranked_entities") or [])[:2]:
        if row.get("priority", 0) <= 0:
            continue

        evidence.extend(_entity_evidence(row))

    return evidence

# ============================================================
# KEEPING THE NARRATIVE HONEST
# ============================================================
#
# The model writes prose. It does not decide anything: evidence
# and recommendations are computed in Python and returned beside
# its answer, and it never sees a path to either.
#
# What it can still do is narrate a severity the record does not
# support - saying a zone is critical when the backend graded it
# normal, or the reverse. The evidence array would contradict the
# answer on the same screen, which is worse than no model at all:
# it teaches the reader that one of the two is unreliable without
# saying which.
#
# A prompt instruction not to do this is a request. Two structural
# measures are not:
#
#   1. The answer carries a verified footer, composed here, naming
#      the status the backend actually assigned. Even fluent
#      output that contradicts the record is corrected by the
#      record printed on top of it.
#   2. If the prose names a severity that disagrees with that
#      status, the prose is discarded and the deterministic answer
#      is used instead, with a caveat saying so.

_SEVERITY_WORDS = (
    ("critical", "critical"),
    ("offline", "offline"),
    ("warning", "warning"),
    ("normal", "normal"),
)

# The status a piece of prose is claiming, if any. Only the worst
# word present counts, because prose says "not critical" as easily
# as "critical" and reading that as a claim would misfire on every
# cautious sentence.
_PRIORITY = (
    "critical",
    "warning",
    "offline",
    "normal",
)


def claimed_severity(text: str) -> Optional[str]:
    """
    The severity a piece of prose asserts, or None if it asserts
    none.

    Deliberately blunt. This is not a natural-language parser and
    does not try to be: it looks for the four status words the
    product uses and takes the most severe one. False positives
    cost a discarded paragraph, which is the cheap direction to
    fail in - the deterministic answer is always available.
    """

    if not text:
        return None

    lowered = text.lower()

    for word in _PRIORITY:
        if re.search(rf"\b{word}\b", lowered):
            return word

    return None


def contradicts_verified_status(
    text: str,
    verified_status: Optional[str],
) -> bool:
    """
    Whether the prose disagrees with the stored status.

    Silent when the status is unknown: an entity the snapshot
    could not resolve has nothing to check against, and inventing
    a contradiction there would replace a good answer with a worse
    one.
    """

    if not verified_status:
        return False

    claimed = claimed_severity(text)

    if claimed is None:
        return False

    return claimed != str(verified_status).lower()


def _verified_footer(
    entity: Optional[Dict[str, Any]],
    snapshot: Dict[str, Any],
) -> str:
    """
    The facts the backend decided, printed under the model's prose.

    Short on purpose. This is an anchor, not a second answer: it
    states what the record says so that a reader, and the person
    presenting, can see at a glance whether the paragraph above it
    agrees.
    """

    lines = ["", "---", "", "Verified by the backend:"]

    if entity is not None:
        status = str(entity.get("status") or "unknown").lower()

        open_count = int(entity.get("open_incident_count") or 0)

        lines.append(
            f"- {entity.get('name')} is {status.upper()}"
        )

        if open_count:
            lines.append(
                f"- {open_count} open incident"
                f"{'s' if open_count != 1 else ''} on this zone"
            )

        for reason in (entity.get("reasons") or [])[:3]:
            lines.append(f"- {reason}")

        return "\n".join(lines)

    counts = snapshot.get("counts") or {}

    total = sum(
        int(value or 0) for value in counts.values()
    )

    lines.append(f"- {total} entities on the campus record")

    for status in _PRIORITY:
        count = counts.get(status)

        if count:
            lines.append(f"- {status}: {count}")

    return "\n".join(lines)
