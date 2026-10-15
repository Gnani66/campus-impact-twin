"""
Tests for the correlation engine (Phase 8).

`evaluate_energy_waste` is pure, so the whole gate is exercised
without a database. The table of scenarios the specification
sets out is reproduced exactly, because those are the cases a
judge will actually ask about: mostly the ones where the engine
must refuse to conclude.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.correlation_rules import (
    CorrelationConfig,
)
from app.services.correlation_service import (
    ROOT_CAUSE_ENERGY_WASTE,
    ROOT_CAUSE_OVER_CAPACITY,
    CorrelationService,
)


NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def ago(seconds: float = 2.0) -> datetime:
    """Recent by default: fresh evidence is the interesting
    case, and freshness is tested separately."""

    return NOW - timedelta(seconds=seconds)


def service() -> CorrelationService:
    return CorrelationService(
        config=CorrelationConfig(
            # A low nominal keeps the expected draw predictable in
            # these tests. The measured baseline is supplied
            # wherever the scenario depends on the ratio.
            nominal_energy_kw_per_capacity=0.05,
        )
    )


# ============================================================
# THE SPECIFICATION'S SCENARIO TABLE
# ============================================================

SCENARIOS = [
    # (label, occupancy, confidence, energy, baseline, capacity,
    #  schedule, expected_status)
    (
        "normal occupied room",
        30, 0.90, 4.0, 2.0, 60, True, "normal",
    ),
    (
        "empty with low energy",
        0, 0.90, 1.8, 2.0, 60, True, "normal",
    ),
    (
        "empty with high energy",
        0, 0.90, 8.0, 2.0, 60, True,
        "confirmed_candidate",
    ),
    (
        "empty high energy but stale telemetry",
        0, 0.90, 8.0, 2.0, 60, True, "needs_review",
    ),
    (
        "empty high energy but low CV confidence",
        0, 0.31, 8.0, 2.0, 60, True, "needs_review",
    ),
    (
        "empty high energy outside schedule",
        0, 0.90, 8.0, 2.0, 60, False, "needs_review",
    ),
    (
        "missing energy",
        0, 0.90, None, 2.0, 60, True, "needs_review",
    ),
    (
        "stale camera",
        0, 0.90, 8.0, 2.0, 60, True, "needs_review",
    ),
    (
        "occupied with high energy is not waste",
        40, 0.90, 8.0, 2.0, 60, True, "normal",
    ),
    (
        "over capacity",
        70, 0.90, 5.0, 2.0, 60, True,
        "confirmed_candidate",
    ),
]


@pytest.mark.parametrize(
    "label,occupancy,confidence,energy,baseline,capacity,"
    "schedule,expected",
    SCENARIOS,
    ids=[row[0] for row in SCENARIOS],
)
def test_specification_scenarios(
    label,
    occupancy,
    confidence,
    energy,
    baseline,
    capacity,
    schedule,
    expected,
):
    """
    One scenario per row of the specification's table.

    The stale-telemetry and stale-camera rows pass explicit old
    timestamps; every other row uses recent evidence so that
    freshness is not the reason a scenario passes or fails.
    """

    stale = "stale" in label

    energy_at = (
        ago(180) if stale else ago(2)
    )
    observation_at = (
        ago(180)
        if label == "stale camera"
        else ago(2)
    )

    result = service().evaluate_energy_waste(
        occupancy=occupancy,
        confidence=confidence,
        energy_kw=energy,
        energy_timestamp=energy_at,
        capacity=capacity,
        schedule_active=schedule,
        observation_timestamp=observation_at,
        baseline_kw=baseline,
        now=NOW,
    )

    assert result["result_status"] == expected, label


# ============================================================
# THE DOCUMENTED EXAMPLE
# ============================================================


def test_documented_example():
    """
    The specification's worked example, end to end.
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=8.5,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "confirmed_candidate"
    assert result["root_cause"] == (
        "Potential energy waste during low occupancy"
    )
    assert result["evidence_score"] == 100.0
    assert result["confidence_score"] == 100.0
    assert result["energy_ratio"] == 4.25
    assert result["expected_energy_kw"] == 2.0
    assert result["occupancy_state"] == (
        "potentially_unoccupied"
    )


def test_root_cause_is_hedged():
    """
    The PRD forbids presenting a modelled condition as a proven
    leak, so the wording can never claim confirmation.
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=8.5,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    root_cause = result["root_cause"].lower()

    assert "potential" in root_cause
    for forbidden in ("confirmed", "leak", "proven"):
        assert forbidden not in root_cause


# ============================================================
# THE JUDGES' QUESTIONS
# ============================================================


def test_missing_energy_is_not_low_energy():
    """
    "How do you know this isn't just a broken sensor?"

    Absence of telemetry must never be read as a low reading.
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=None,
        energy_timestamp=None,
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "needs_review"
    assert result["root_cause"] is None
    assert result["confidence_score"] == 0.0


def test_low_confidence_empty_room_is_not_an_empty_room():
    """
    A "no people" reading the camera is unsure about is not
    evidence of an empty room.
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.31,
        energy_kw=8.0,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "needs_review"

    names = {
        check["name"]: check
        for check in result["evidence"]
    }

    assert names["vision_reliable"]["passed"] is False


def test_outside_schedule_is_not_waste():
    """
    The building may be cleaning, maintaining or securing
    itself. Flagging that is flagging it for doing its job.
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=8.0,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=False,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "needs_review"
    assert result["root_cause"] is None


def test_no_camera_at_all_is_review():
    """
    With no observation the engine cannot establish occupancy,
    and must not assume the room is empty.
    """

    result = service().evaluate_energy_waste(
        occupancy=None,
        confidence=None,
        energy_kw=8.0,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=None,
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "needs_review"


def test_unknown_capacity_is_review():
    """
    Without capacity, "low occupancy" cannot be established.
    Assuming it would manufacture findings.
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=8.0,
        energy_timestamp=ago(2),
        capacity=None,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "needs_review"


def test_every_check_is_reported():
    """
    All six conditions are reported whether or not they were
    reached, so the response shows the whole picture rather
    than stopping at the first failure.
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=None,
        energy_timestamp=None,
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert len(result["evidence"]) == 6

    names = {c["name"] for c in result["evidence"]}

    assert names == {
        "vision_reliable",
        "observation_fresh",
        "energy_available",
        "schedule_active",
        "energy_anomaly",
        "occupancy_low",
    }


def test_each_failure_names_its_own_reason():
    """
    A downgrade must be explicable. Which check failed is the
    difference between "the camera is unsure" and "the energy
    feed is dead".
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=None,
        energy_timestamp=None,
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    failures = [
        c for c in result["evidence"] if not c["passed"]
    ]

    assert any(
        "energy" in c["name"] for c in failures
    )


# ============================================================
# OVER CAPACITY
# ============================================================


def test_over_capacity_is_its_own_root_cause():
    """
    A room above capacity is a ventilation and safety concern.
    Calling it energy waste would send whoever reads the alert
    to the wrong subsystem.
    """

    result = service().evaluate_energy_waste(
        occupancy=70,
        confidence=0.90,
        energy_kw=5.0,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "confirmed_candidate"
    assert result["root_cause"] == ROOT_CAUSE_OVER_CAPACITY
    assert result["occupancy_state"] == "over_capacity"


def test_over_capacity_still_needs_evidence():
    """
    Over capacity is not reported from a stale or unconfident
    reading either.
    """

    result = service().evaluate_energy_waste(
        occupancy=70,
        confidence=0.20,
        energy_kw=5.0,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "needs_review"


# ============================================================
# HIGH ENERGY IN AN OCCUPIED ROOM
# ============================================================


def test_busy_room_is_not_reported_as_waste():
    """
    8 kW in a room holding 40 of 60 people is a busy room, not a
    fault. High energy alone is not waste.
    """

    result = service().evaluate_energy_waste(
        occupancy=40,
        confidence=0.90,
        energy_kw=8.0,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "normal"
    assert result["root_cause"] is None
    assert result["confidence_score"] == 0.0


# ============================================================
# NOMINAL FALLBACK
# ============================================================


def test_nominal_expectation_still_gates():
    """
    A zone with no history is evaluated against a nominal, but
    that is the weakest path and still requires a confident,
    fresh camera and an active schedule.
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=8.0,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=None,
        now=NOW,
    )

    assert result["result_status"] == "confirmed_candidate"
    assert result["expected_energy_kw"] == 3.0


def test_specification_example_without_baseline():
    """
    The specification's own root-cause test supplies no
    baseline at all and still expects a candidate.
    """

    result = CorrelationService().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=8.0,
        energy_timestamp=datetime.now(
            timezone.utc
        ).isoformat(),
        capacity=60,
        schedule_active=True,
        observation_timestamp=datetime.now(
            timezone.utc
        ).isoformat(),
    )

    assert result["result_status"] == "confirmed_candidate"
    assert result["root_cause"] == ROOT_CAUSE_ENERGY_WASTE


def test_iso_string_timestamps_are_accepted():
    """
    Stored timestamps arrive as ISO strings, not datetimes.
    """

    stamp = datetime.now(timezone.utc).isoformat()

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=8.0,
        energy_timestamp=stamp,
        capacity=60,
        schedule_active=True,
        observation_timestamp=stamp,
        baseline_kw=2.0,
    )

    assert result["result_status"] == "confirmed_candidate"


# ============================================================
# ROBUSTNESS
# ============================================================


def test_future_timestamps_are_refused():
    """
    A source clock running fast must not manufacture
    permanently fresh evidence.
    """

    future = datetime.now(timezone.utc) + timedelta(hours=1)

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=8.0,
        energy_timestamp=future,
        capacity=60,
        schedule_active=True,
        observation_timestamp=future,
        baseline_kw=2.0,
    )

    assert result["result_status"] == "needs_review"


def test_negative_energy_is_refused():
    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=-3.0,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    assert result["result_status"] == "needs_review"


def test_string_inputs_are_coerced():
    """
    `numeric` columns come back from PostgREST as strings
    depending on the driver, so the gate has to cope.
    """

    result = service().evaluate_energy_waste(
        occupancy="0",
        confidence="0.90",
        energy_kw="8.5",
        energy_timestamp=ago(2),
        capacity="60",
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw="2.0",
        now=NOW,
    )

    assert result["result_status"] == "confirmed_candidate"


def test_internal_keys_never_reach_the_caller():
    """
    The response is persisted verbatim, so nothing internal may
    appear in it.
    """

    result = service().evaluate_energy_waste(
        occupancy=0,
        confidence=0.90,
        energy_kw=8.0,
        energy_timestamp=ago(2),
        capacity=60,
        schedule_active=True,
        observation_timestamp=ago(2),
        baseline_kw=2.0,
        now=NOW,
    )

    for key in ("_checks", "_observation_id", "blocking_reason"):
        assert key not in result