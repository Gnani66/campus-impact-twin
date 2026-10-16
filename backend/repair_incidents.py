"""
Repairs incidents written while the evidence-nesting bug was live.

`IntelligenceService._refresh_incident` used to store the whole
previous evidence record inside its own `observations` list, so
every refresh added a level of nesting with no bound. Two kinds of
damage are left in the table:

1. Deeply nested evidence. Depth reached 200 and a single row grew
   past 60 kB. The nesting is no longer produced (see the fix and
   its tests in `tests/test_intelligence_service.py`), but rows
   written before it still carry it, and they bloat every payload
   that includes them.

2. Duplicate open incidents. Once a row was nested deeply enough,
   the client could no longer parse it and returned raw text, so
   `_find_open_incident` failed and a new incident was written for
   every reading. A single temperature breach produced fifteen open
   incidents in fifteen seconds.

The repair reconstructs what a working de-duplication pass would
have produced:

  - the observations list is rewritten as flat projections;
  - each chain of duplicates collapses into its first incident,
    which keeps the worst impact and the latest measurements seen
    across the chain, and the timeline of the whole chain;
  - the rest are marked `dismissed`, which is honest - they were
    never separate events - and keeps them auditable rather than
    deleting them.

Chains are anchored where the service anchors them: the stored
incident keeps its original `detected_at`, so a reading more than
`DEDUP_WINDOW_SECONDS` after that point starts a new incident even
while the condition persists. Only members within that window of
the chain's first incident are collapsed.

Idempotent, and a dry run unless `--apply` is passed. Nothing
downstream reads the nested shape; the `observations` constant
elsewhere in the codebase is a table name, not this key.

    python repair_incidents.py            # report only
    python repair_incidents.py --apply    # write
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from app.db.supabase import get_supabase
from app.services.intelligence_service import (
    DEDUP_WINDOW_SECONDS,
    OPEN_STATUSES,
)

# What one row is allowed to grow to. A flat record with fifty
# observations of four scalars is well under a kilobyte.
MAX_OBSERVATIONS = 50


# ============================================================
# EVIDENCE
# ============================================================


def _epoch(value: Any) -> float:
    parsed = datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.timestamp()


def _observation(record: Dict[str, Any]) -> Dict[str, Any]:
    """The flat shape a stored observation should have."""

    return {
        "observed_at": record.get("observed_at"),
        "value": record.get("value"),
        "metric": record.get("metric"),
        "impact_score": record.get("impact_score"),
    }


def depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max(
            [depth(item) for item in value.values()] or [0]
        )

    if isinstance(value, list):
        return 1 + max(
            [depth(item) for item in value] or [0]
        )

    return 0


def is_nested(evidence: Any) -> bool:
    """
    True when an observation holds a record inside it, which is
    the signature the old code left behind.
    """

    if not evidence:
        return False

    return any(
        isinstance(item, dict) and "observations" in item
        for item in evidence[0].get("observations") or []
    )


def flatten(evidence: Any) -> List[Dict[str, Any]]:
    """
    Rebuilds evidence as one flat record, keeping the timeline.

    Every observation currently stored is projected down to its
    scalars, oldest first. A record whose list is empty carries
    its own observation over, so a timeline never starts empty.
    """

    record = (evidence or [{}])[0]

    observations = [
        _observation(item)
        for item in record.get("observations") or []
    ]

    if (
        not observations
        and record.get("observed_at") is not None
    ):
        observations.append(_observation(record))

    rebuilt = dict(record)
    rebuilt["observations"] = observations[-MAX_OBSERVATIONS:]

    return [rebuilt]


# ============================================================
# DEDUPLICATION
# ============================================================


def _chain_members(
    incidents: List[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    """
    Groups open incidents the way the service groups them, then
    splits each group where the de-duplication window ends.
    """

    groups: Dict[
        Tuple[Any, Any, Any], List[Dict[str, Any]]
    ] = defaultdict(list)

    for incident in incidents:
        if incident.get("status") not in OPEN_STATUSES:
            continue

        rule = (incident.get("evidence") or [{}])[0].get(
            "rule"
        )

        if rule is None:
            continue

        groups[
            (
                incident.get("zone_id"),
                incident.get("category"),
                rule,
            )
        ].append(incident)

    chains = []

    for members in groups.values():
        ordered = sorted(
            members, key=lambda item: item["detected_at"]
        )

        current: List[Dict[str, Any]] = []

        for incident in ordered:
            # The stored incident keeps its original detected_at,
            # so the window is measured from the start of the
            # chain, not from the incident kept before this one.
            if not current or (
                _epoch(incident["detected_at"])
                <= _epoch(current[0]["detected_at"])
                + DEDUP_WINDOW_SECONDS
            ):
                current.append(incident)
                continue

            chains.append(current)
            current = [incident]

        if current:
            chains.append(current)

    return chains


def merge_chain(
    chain: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], float, List[Dict[str, Any]]]:
    """
    Collapses one chain into the incident a working run would
    have stored.

    The first incident keeps its identity and its `detected_at`;
    it takes the latest measurements, the worst impact and the
    whole timeline.
    """

    ordered = sorted(
        chain, key=lambda item: item["detected_at"]
    )

    kept, *duplicates = ordered

    observations: List[Dict[str, Any]] = []
    worst = 0.0

    for incident in ordered:
        evidence = incident.get("evidence") or [{}]
        record = evidence[0]

        observations.extend(
            record.get("observations") or []
        )
        observations.append(_observation(record))

        worst = max(
            worst, float(incident.get("impact_score") or 0.0)
        )

    latest = (ordered[-1].get("evidence") or [{}])[0]

    rebuilt = dict(latest)
    rebuilt["observations"] = observations[
        -MAX_OBSERVATIONS:
    ]

    return kept, worst, [rebuilt], duplicates


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Repair nested evidence and duplicate incidents."
        )
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the repairs instead of reporting them.",
    )

    arguments = parser.parse_args()

    incidents = (
        get_supabase()
        .table("incidents")
        .select(
            "id,title,status,category,zone_id,detected_at,"
            "impact_score,evidence"
        )
        .execute()
        .data
    )

    # Flatten in memory first, so de-duplication reads the same
    # shape whatever each row arrived as.
    flattened = {
        incident["id"]: flatten(incident.get("evidence"))
        for incident in incidents
        if is_nested(incident.get("evidence"))
    }

    for incident in incidents:
        if incident["id"] in flattened:
            incident["evidence"] = flattened[incident["id"]]

    updates: Dict[str, Dict[str, Any]] = {
        incident_id: {"evidence": evidence}
        for incident_id, evidence in flattened.items()
    }

    now = datetime.now(timezone.utc).isoformat()
    dismissed = 0

    for chain in _chain_members(incidents):
        if len(chain) < 2:
            continue

        kept, worst, merged, duplicates = merge_chain(chain)

        entry = updates.setdefault(kept["id"], {})
        entry["evidence"] = merged
        entry["impact_score"] = worst

        for duplicate in duplicates:
            updates[duplicate["id"]] = {
                "status": "dismissed",
                "resolved_at": now,
            }

            dismissed += 1

    print(f"incidents: {len(incidents)}")

    if not flattened and not dismissed:
        print("nothing to repair")
        return

    if flattened:
        print(f"\nnested evidence ({len(flattened)}):")

        for incident_id, evidence in flattened.items():
            print(
                f"  {incident_id[:8]}  "
                f"depth {depth(evidence)}  "
                f"{len(json.dumps(evidence))} bytes"
            )

    if dismissed:
        print(
            f"\nduplicate open incidents dismissed: "
            f"{dismissed}"
        )

    if not arguments.apply:
        print("\ndry run: nothing written (pass --apply)")
        return

    client = get_supabase()

    for incident_id, payload in updates.items():
        (
            client.table("incidents")
            .update(payload)
            .eq("id", incident_id)
            .execute()
        )

    print(f"\nwritten: {len(updates)} incidents updated")


if __name__ == "__main__":
    main()
