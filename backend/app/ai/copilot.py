"""
Intent classification and context building (Phase 13).

INTENT IS CLASSIFIED DETERMINISTICALLY, AND THE ORDER IS LOAD-BEARING.

The local model is not asked what a request means. A 3B model
asked to route a question will occasionally route a safety
question into a generic bucket, and the consequence is answering a
request the operator did not make, confidently. Keyword matching
is boring, testable and predictable, which is the entire point.

The cascade is ordered so that EXPLANATION is checked before
RECOMMENDATION. "Why should we increase ventilation?" contains
both words; it is a request for a reason, not for a suggestion,
and checking RECOMMENDATION first would answer the wrong
question.

Matching is on word boundaries rather than raw substrings, so
"why" does not fire inside an unrelated word and "status" does
not fire inside a pasted status code.
"""

import re
from typing import Any, Dict, List, Optional


# ============================================================
# INTENTS
# ============================================================

INTENT_OVERVIEW = "OVERVIEW"
INTENT_ENTITY_ANALYSIS = "ENTITY_ANALYSIS"
INTENT_INCIDENT_ANALYSIS = "INCIDENT_ANALYSIS"
INTENT_RECOMMENDATION = "RECOMMENDATION"
INTENT_WHAT_IF = "WHAT_IF"
INTENT_EXPLANATION = "EXPLANATION"
INTENT_UNKNOWN = "UNKNOWN"

ALL_INTENTS = (
    INTENT_OVERVIEW,
    INTENT_ENTITY_ANALYSIS,
    INTENT_INCIDENT_ANALYSIS,
    INTENT_RECOMMENDATION,
    INTENT_WHAT_IF,
    INTENT_EXPLANATION,
    INTENT_UNKNOWN,
)


# Ordered. EXPLANATION deliberately precedes RECOMMENDATION: a
# question beginning "why should we..." is asking for a
# justification, and answering with a suggestion instead would be
# a confident non-answer.
_CASCADE = (
    (
        INTENT_OVERVIEW,
        (
            "what needs attention",
            "what is happening",
            "what needs my attention",
            "overview",
            "any issues",
            "anything wrong",
            "current status",
            "status",
            "how are we doing",
            "summarise",
            "summarize",
            "brief",
            "attention",
            "right now",
        ),
    ),
    (
        INTENT_EXPLANATION,
        (
            "why",
            "explain",
            "reason",
            "how come",
            "what happened",
            "what caused",
            "justify",
            "critical",
            "what makes",
        ),
    ),
    (
        INTENT_WHAT_IF,
        (
            "what if",
            "what-if",
            "simulate",
            "would it",
            "if we set",
            "suppose we",
        ),
    ),
    (
        INTENT_RECOMMENDATION,
        (
            "recommend",
            "recommendation",
            "what should",
            "what can we do",
            "what could we do",
            "suggest",
            "suggestion",
            "action",
            "fix",
            "resolve",
            "improve",
            "reduce",
            "mitigate",
        ),
    ),
    (
        INTENT_INCIDENT_ANALYSIS,
        (
            "incident",
            "alert",
            "alerts",
            "issue",
            "issues",
            "problem",
            "problems",
        ),
    ),
    (
        INTENT_ENTITY_ANALYSIS,
        (
            "tell me about",
            "how is",
            "status of",
            "details",
            "what is happening in",
        ),
    ),
)


def _matches(text: str, phrase: str) -> bool:
    """
    Whole-phrase match with word boundaries.

    Uses a regex escape so a phrase containing punctuation cannot
    be misread as a pattern, and anchors on word characters so
    "why" does not match inside "whyway".
    """

    escaped = re.escape(phrase).replace(r"\ ", r"\s+")

    return (
        re.search(
            rf"(?:^|\b){escaped}(?:$|\b)", text
        )
        is not None
    )


def classify_intent(
    message: str,
    entity_id: Optional[str] = None,
) -> str:
    """
    Returns the intent for a message.

    A message that names an entity and asks something specific is
    an entity analysis even if it trips a broader keyword, because
    the caller has already scoped the question and answering about
    the whole campus would ignore that scope.
    """

    text = (message or "").lower().strip()

    if not text:
        return INTENT_UNKNOWN

    for intent, phrases in _CASCADE:
        for phrase in phrases:
            if _matches(text, phrase):
                # An entity-scoped request is about that entity
                # unless it asked something campus-wide.
                if (
                    intent
                    in (
                        INTENT_INCIDENT_ANALYSIS,
                        INTENT_ENTITY_ANALYSIS,
                    )
                    and entity_id
                ):
                    return INTENT_ENTITY_ANALYSIS

                return intent

    if entity_id:
        return INTENT_ENTITY_ANALYSIS

    return INTENT_UNKNOWN


# ============================================================
# CONTEXT BUILDING
# ============================================================


def format_metrics(metrics: Dict[str, Any]) -> List[str]:
    """
    Renders readings as short labelled facts.

    A reading this deployment does not have is rendered as
    "not measured" rather than omitted. Omitting it would let a
    reader assume the value is fine; saying so explicitly is the
    honest position and matches what the digital twin panel
    already shows.
    """

    units = {
        "temperature": "C",
        "humidity": "%",
        "eco2": "ppm",
        "energy": "kW",
    }

    order = (
        "temperature",
        "humidity",
        "eco2",
        "occupancy",
        "occupancy_ratio",
        "energy",
        "aqi",
        "sound",
    )

    lines = []

    for key in order:
        value = metrics.get(key)

        if value is None:
            lines.append(f"- {key}: not measured")

            continue

        if key == "occupancy_ratio":
            lines.append(
                f"- occupancy: {round(float(value) * 100)}% "
                "of capacity"
            )
            continue

        number = (
            f"{value:.0f}"
            if float(value).is_integer()
            else f"{value:.2f}"
        )

        suffix = units.get(key, "")

        label = (
            "occupancy"
            if key == "occupancy"
            else key
        )

        lines.append(
            f"- {label}: {number}{(' ' + suffix) if suffix else ''}"
        )

    return lines


def summarise_issues(
    issues: List[str],
) -> List[Any]:
    """
    Groups identical incident titles and counts them.

    An ungrouped list of four identical "Overheating in an
    occupied zone (critical)" lines invites a reader, human or
    model, to count them and report four problems. That number
    was never measured; it is an artefact of how the incidents
    were listed.

    So the count is stated explicitly and the duplicates are
    collapsed. The model is then given the number rather than
    left to derive it from a list length, which is the only
    reliable way to stop it deriving it wrongly.
    """

    counts: Dict[str, int] = {}

    for issue in issues or []:
        text = str(issue).strip()

        if text:
            counts[text] = counts.get(text, 0) + 1

    return list(counts.items())


def format_issue_lines(
    issues: List[str],
) -> List[str]:
    """
    Issue lines with their counts attached.
    """

    rows = summarise_issues(issues)

    if not rows:
        return []

    total = sum(count for _, count in rows)

    lines = [f"Open incidents recorded: {total}"]

    for text, count in rows:
        suffix = f" (x{count})" if count > 1 else ""

        lines.append(f"- {text}{suffix}")

    return lines


def build_entity_context(entity: Dict[str, Any]) -> str:
    """
    A factual brief for one entity.

    Everything here is a stored reading or a computed status.
    The model is asked to explain this, not to reason about what
    it might mean, so the facts arrive pre-computed and the
    thresholds are stated explicitly rather than left for the
    model to infer.
    """

    if not entity:
        return ""

    metrics = entity.get("metrics") or {}

    lines = [
        f"Entity: {entity.get('name')} ({entity.get('code')})",
        f"Type: {entity.get('type')}",
        f"Backend-assigned status: {entity.get('status')}",
        "",
        "Verified readings:",
        *format_metrics(metrics),
    ]

    reasons = entity.get("reasons") or []

    if reasons:
        lines.extend(
            [
                "",
                "Why the backend assigned that status:",
                *[f"- {reason}" for reason in reasons],
            ]
        )

    issues = entity.get("active_issues") or []

    if issues:
        lines.extend(
            [
                "",
                *format_issue_lines(issues),
            ]
        )

    root_cause = entity.get("root_cause")

    if root_cause:
        lines.extend(
            [
                "",
                f"Latest correlation finding: {root_cause}",
            ]
        )

    observed = entity.get("observed_at")

    if observed:
        lines.extend(
            [
                "",
                f"Data timestamp (UTC): {observed}",
            ]
        )

    return "\n".join(lines)


def build_overview_context(snapshot: Dict[str, Any]) -> str:
    """
    A factual brief for the whole campus.

    Ordered by the deterministic priority the backend computed,
    so the most operationally significant entity leads. The model
    restates this ordering; it does not produce it.
    """

    counts = snapshot.get("counts") or {}

    lines = [
        "Campus overview",
        "",
        f"Entities: {snapshot.get('total_entities', 0)} total"
        f" | {counts.get('normal', 0)} normal"
        f" | {counts.get('warning', 0)} warning"
        f" | {counts.get('critical', 0)} critical"
        f" | {counts.get('offline', 0)} offline",
    ]

    ranked = snapshot.get("ranked_entities") or []

    if not ranked:
        lines.extend(
            [
                "",
                "No entity is currently outside its "
                "operational thresholds.",
            ]
        )

        return "\n".join(lines)

    lines.extend(["", "Entities requiring attention, most operationally significant first:"])

    for index, entity in enumerate(ranked[:5], start=1):
        metrics = entity.get("metrics") or {}

        head = (
            f"{index}. {entity.get('name')} "
            f"({entity.get('code')}) - "
            f"{str(entity.get('status')).upper()}"
        )

        lines.append(head)

        for fact in format_metrics(metrics):
            lines.append(f"   {fact}")

        for reason in (entity.get("reasons") or [])[:2]:
            lines.append(f"   reason: {reason}")

        people = metrics.get("occupancy")

        if people is not None:
            lines.append(
                f"   people affected: {int(people)}"
            )

        lines.append("")

    top = snapshot.get("top_priority")

    if top:
        lines.append(
            "Highest priority entity: "
            f"{top.get('name')} ({top.get('code')}) "
            f"- priority score {top.get('priority')}"
        )

    offline = [
        entity
        for entity in (snapshot.get("entities") or [])
        if entity.get("status") == "offline"
    ]

    if offline:
        names = ", ".join(
            entity.get("code") or "?"
            for entity in offline
        )

        lines.extend(
            [
                "",
                f"Telemetry unavailable for: {names}. "
                "These are not healthy readings; they are "
                "missing readings.",
            ]
        )

    return "\n".join(lines)