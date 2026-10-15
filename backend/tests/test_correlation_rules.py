"""
Tests for the correlation evidence gate.

The gate is the product. If it is wrong, the system either
raises incidents that do not exist or stays silent while a real
one goes unnoticed, so these tests lean on the cases that must
be refused rather than the ones that must fire.

Everything here is pure: no database, no model, no network.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.correlation_rules import (
    DEFAULT_CORRELATION_CONFIG,
    CorrelationConfig,
    calculate_confidence_score,
    calculate_energy_ratio,
    calculate_evidence_score,
    calculate_occupancy_ratio,
    check_energy_anomaly,
    check_energy_evidence,
    check_observation_freshness,
    check_occupancy_low,
    check_schedule_active,
    check_vision_evidence,
    expected_energy_kw,
    occupancy_state,
    parse_timestamp,
)


NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def ago(seconds: float) -> datetime:
    return NOW - timedelta(seconds=seconds)


# ============================================================
# OCCUPANCY RATIO
# ============================================================


def test_occupancy_ratio():
    result = calculate_occupancy_ratio(
        occupancy=10,
        capacity=50,
    )

    assert result == 0.2


def test_occupancy_ratio_without_capacity():
    """
    Unknown capacity is not the same as an empty room, and the
    caller has to be able to tell them apart.
    """

    result = calculate_occupancy_ratio(
        occupancy=10,
        capacity=None,
    )

    assert result is None


def test_occupancy_ratio_zero_capacity():
    """A capacity of zero makes the ratio undefined."""

    assert (
        calculate_occupancy_ratio(
            occupancy=10, capacity=0
        )
        is None
    )


def test_occupancy_ratio_negative_capacity():
    """
    A negative capacity is nonsense. Clamping it would silently
    invent a full or empty room instead of surfacing the
    misconfiguration.
    """

    assert (
        calculate_occupancy_ratio(
            occupancy=10, capacity=-5
        )
        is None
    )


def test_occupancy_ratio_allows_over_capacity():
    """
    Over capacity is a real state with a different root cause,
    so the ratio must be allowed past 1.0 rather than clamped.
    """

    assert (
        calculate_occupancy_ratio(
            occupancy=70, capacity=60
        )
        == pytest.approx(1.1667, abs=1e-3)
    )


def test_occupancy_ratio_empty_room():
    assert (
        calculate_occupancy_ratio(
            occupancy=0, capacity=60
        )
        == 0.0
    )


# ============================================================
# TIMESTAMP PARSING
# ============================================================


def test_parse_both_utc_spellings():
    """
    PostgREST has been seen returning `+00:00` where an upload
    sent `Z`. Both must land on the same instant.
    """

    zulu = parse_timestamp("2026-10-16T12:00:00Z")
    offset = parse_timestamp("2026-10-16T12:00:00+00:00")

    assert zulu == offset == NOW


def test_parse_naive_is_utc():
    assert (
        parse_timestamp("2026-10-16T12:00:00") == NOW
    )


def test_parse_garbage_is_none():
    """Missing evidence is reported, not raised."""

    assert parse_timestamp("not-a-time") is None
    assert parse_timestamp("") is None
    assert parse_timestamp(None) is None


# ============================================================
# VISION EVIDENCE
# ============================================================


def test_vision_evidence_passes():
    config = CorrelationConfig()

    result = check_vision_evidence(
        occupancy=0,
        confidence=0.9,
        config=config,
    )

    assert result.passed is True
    assert result.score == 1.0


def test_vision_evidence_low_confidence_fails():
    """
    Below the threshold the camera is guessing. Reading it as
    an empty room is the exact failure the gate exists to stop.
    """

    result = check_vision_evidence(
        occupancy=0,
        confidence=0.31,
    )

    assert result.passed is False
    assert "0.31" in result.reason


def test_vision_evidence_threshold_is_inclusive():
    """Exactly at the threshold is trusted, not refused."""

    assert check_vision_evidence(
        occupancy=0, confidence=0.55
    ).passed


def test_vision_evidence_missing_count():
    assert not check_vision_evidence(
        occupancy=None, confidence=0.9
    ).passed


def test_vision_evidence_missing_confidence():
    assert not check_vision_evidence(
        occupancy=0, confidence=None
    ).passed


def test_vision_evidence_rejects_impossible_confidence():
    """
    A confidence outside 0..1 means the detector or its
    transport is broken, which is worth naming rather than
    folding into an ordinary low-confidence reading.
    """

    result = check_vision_evidence(
        occupancy=0, confidence=1.4
    )

    assert result.passed is False
    assert "outside 0..1" in result.reason


def test_vision_evidence_empty_room_at_high_confidence_passes():
    """
    Zero people seen clearly is a legitimate, strong reading.
    The gate must not treat the number itself as suspicious.
    """

    result = check_vision_evidence(
        occupancy=0, confidence=0.95
    )

    assert result.passed is True


# ============================================================
# FRESHNESS
# ============================================================


def test_fresh_observation_passes():
    result = check_observation_freshness(
        ago(5), NOW, DEFAULT_CORRELATION_CONFIG
    )

    assert result.passed is True


def test_stale_observation_fails():
    result = check_observation_freshness(
        ago(180), NOW, DEFAULT_CORRELATION_CONFIG
    )

    assert result.passed is False
    assert "180s" in result.reason


def test_observation_freshness_boundary():
    config = CorrelationConfig(
        observation_max_age_seconds=20
    )

    assert check_observation_freshness(
        ago(19), NOW, config
    ).passed
    assert not check_observation_freshness(
        ago(21), NOW, config
    ).passed


def test_future_observation_fails():
    """
    A timestamp ahead of now means a clock disagreement, not a
    very fresh reading. Accepting it would make broken evidence
    look infinitely current.
    """

    result = check_observation_freshness(
        ago(-60), NOW, DEFAULT_CORRELATION_CONFIG
    )

    assert result.passed is False
    assert "future" in result.reason


def test_missing_observation_timestamp_fails():
    assert not check_observation_freshness(
        None, NOW, DEFAULT_CORRELATION_CONFIG
    ).passed


# ============================================================
# ENERGY EVIDENCE
# ============================================================


def test_energy_available_passes():
    result = check_energy_evidence(
        8.5, ago(3), NOW, DEFAULT_CORRELATION_CONFIG
    )

    assert result.passed is True


def test_missing_energy_fails():
    """
    The judge scenario: no energy telemetry must not be treated
    as low energy. Absence is not a measurement.
    """

    result = check_energy_evidence(
        None, ago(3), NOW, DEFAULT_CORRELATION_CONFIG
    )

    assert result.passed is False
    assert "No energy" in result.reason


def test_stale_energy_fails():
    result = check_energy_evidence(
        8.5, ago(180), NOW, DEFAULT_CORRELATION_CONFIG
    )

    assert result.passed is False
    assert "180s" in result.reason


def test_energy_telemetry_boundary():
    config = CorrelationConfig(
        telemetry_max_age_seconds=30
    )

    assert check_energy_evidence(
        8.0, ago(29), NOW, config
    ).passed
    assert not check_energy_evidence(
        8.0, ago(31), NOW, config
    ).passed


def test_negative_energy_fails():
    """
    Negative draw means a faulty meter. It must not be treated
    as a very efficient room.
    """

    result = check_energy_evidence(
        -1.0, ago(2), NOW, DEFAULT_CORRELATION_CONFIG
    )

    assert result.passed is False
    assert "faulty meter" in result.reason


def test_nan_energy_fails():
    result = check_energy_evidence(
        float("nan"), ago(2), NOW, DEFAULT_CORRELATION_CONFIG
    )

    assert result.passed is False


def test_string_energy_is_coerced():
    """PostgREST may return a numeric column as a string."""

    result = check_energy_evidence(
        "8.5", ago(2), NOW, DEFAULT_CORRELATION_CONFIG
    )

    assert result.passed is True


# ============================================================
# SCHEDULE
# ============================================================


def test_schedule_active_passes():
    assert check_schedule_active(True).passed


def test_schedule_inactive_fails():
    """
    Outside hours the room may be cleaned, maintained or
    secured, all of which draw legitimately.
    """

    result = check_schedule_active(False)

    assert result.passed is False
    assert "maintenance" in result.reason


# ============================================================
# ENERGY ANOMALY
# ============================================================


def test_energy_anomaly_detected():
    assert check_energy_anomaly(4.25).passed


def test_energy_below_threshold():
    assert not check_energy_anomaly(1.2).passed


def test_energy_anomaly_threshold_is_inclusive():
    assert check_energy_anomaly(1.50).passed
    assert not check_energy_anomaly(1.49).passed


def test_energy_anomaly_needs_a_ratio():
    assert not check_energy_anomaly(None).passed


# ============================================================
# OCCUPANCY LOW
# ============================================================


def test_occupancy_low_passes():
    assert check_occupancy_low(0.05).passed


def test_occupancy_high_fails():
    """
    This is what keeps the busiest room in the building from
    being reported as its biggest problem.
    """

    result = check_occupancy_low(0.5)

    assert result.passed is False


def test_occupancy_unknown_capacity_fails():
    """
    Assuming a zone is empty when its capacity is unknown would
    manufacture findings.
    """

    result = check_occupancy_low(None)

    assert result.passed is False
    assert "capacity is unknown" in result.reason


# ============================================================
# RATIOS AND EXPECTATIONS
# ============================================================


def test_energy_ratio():
    assert calculate_energy_ratio(8.5, 2.0) == 4.25


def test_energy_ratio_needs_expectation():
    """A ratio from a guessed expectation would be invented."""

    assert calculate_energy_ratio(8.5, None) is None
    assert calculate_energy_ratio(None, 2.0) is None


def test_energy_ratio_zero_expectation():
    assert calculate_energy_ratio(8.5, 0) is None


def test_expected_prefers_measured_baseline():
    assert expected_energy_kw(8.5, 2.0, 60) == 2.0


def test_expected_falls_back_to_capacity_nominal():
    """
    A zone with no history still needs an expectation, or it can
    never be judged. The nominal is a design figure, not a
    measurement, and every other gate check still applies.
    """

    result = expected_energy_kw(8.0, None, 60)

    assert result == pytest.approx(3.0)


def test_expected_is_none_without_any_basis():
    assert expected_energy_kw(8.0, None, None) is None


def test_invalid_baseline_falls_through():
    assert expected_energy_kw(
        8.0, 0.0, 60
    ) == pytest.approx(3.0)


# ============================================================
# SCORING
# ============================================================


def test_evidence_score_all_pass():
    checks = [
        check_vision_evidence(0, 0.9),
        check_schedule_active(True),
    ]

    assert calculate_evidence_score(checks) == 100.0


def test_evidence_score_partial():
    """
    A partial score alongside `needs_review` says how far off
    the mark the evidence was. A flat zero loses that.
    """

    checks = [
        check_vision_evidence(0, 0.9),
        check_vision_evidence(0, 0.1),
    ]

    assert calculate_evidence_score(checks) == 50.0


def test_evidence_score_empty():
    assert calculate_evidence_score([]) == 0.0


def test_confidence_score_saturates():
    """
    A strong finding with a very confident camera reaches 100
    and is capped there, because above 100 would be an invalid
    claim rather than a stronger one.
    """

    score = calculate_confidence_score(0.90, 4.25)

    assert score == 100.0


def test_confidence_score_weak():
    score = calculate_confidence_score(0.60, 1.60)

    assert 0 < score < 100


def test_confidence_score_falls_with_worse_inputs():
    strong = calculate_confidence_score(0.90, 4.25)
    weak = calculate_confidence_score(0.56, 1.55)

    assert weak < strong


def test_confidence_score_handles_missing_inputs():
    assert calculate_confidence_score(None, None) == 0.0


# ============================================================
# OCCUPANCY STATE
# ============================================================


def test_occupancy_state_naming():
    assert occupancy_state(0.05) == "potentially_unoccupied"
    assert occupancy_state(0.5) == "occupied"
    assert occupancy_state(1.2) == "over_capacity"
    assert occupancy_state(None) == "unknown"


def test_occupancy_state_is_hedged():
    """
    The wording is constrained: a camera count is evidence about
    a room, not proof of it. The hedge is the prefix, so the
    state must never be reported as a bare "unoccupied".
    """

    state = occupancy_state(0.05)

    assert state.startswith("potentially_")
    assert state != "unoccupied"