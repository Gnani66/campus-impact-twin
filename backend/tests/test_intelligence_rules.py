"""
Tests for the deterministic campus intelligence rules.

No database, no mocks: the rules are pure functions, so they are
tested by calling them.
"""

import pytest

from app.core.intelligence_rules import (
    CO2_CRITICAL,
    CO2_HIGH,
    ENERGY_MULTIPLIER_HIGH,
    HUMIDITY_HIGH,
    HUMIDITY_LOW,
    TEMPERATURE_CRITICAL,
    TEMPERATURE_HIGH,
    evaluate_co2,
    evaluate_energy,
    evaluate_humidity,
    evaluate_metric,
    evaluate_occupancy,
    evaluate_temperature,
)


class TestTemperature:
    def test_below_threshold_does_not_fire(self):
        assert (
            evaluate_temperature(
                TEMPERATURE_HIGH - 0.1, occupancy=20
            )
            is None
        )

    def test_exact_threshold_fires(self):
        result = evaluate_temperature(
            TEMPERATURE_HIGH, occupancy=20, capacity=60
        )

        assert result is not None
        assert result.category == "environment"
        assert result.severity == "high"

    def test_critical_threshold_raises_severity(self):
        result = evaluate_temperature(
            TEMPERATURE_CRITICAL, occupancy=20
        )

        assert result.severity == "critical"
        assert result.impact_score >= 80.0

    def test_empty_zone_does_not_fire(self):
        """The single most important guard: an empty zone at
        30 C is a closed door, not a failure."""

        assert (
            evaluate_temperature(30.0, occupancy=0)
            is None
        )

    def test_missing_occupancy_does_not_fire(self):
        assert (
            evaluate_temperature(30.0, occupancy=None)
            is None
        )

    def test_impact_grows_with_exceedance(self):
        low = evaluate_temperature(
            28.5, occupancy=10
        )
        high = evaluate_temperature(
            31.0, occupancy=10
        )

        assert high.impact_score > low.impact_score

    def test_impact_within_bounds(self):
        result = evaluate_temperature(
            40.0, occupancy=10
        )

        assert 0.0 <= result.impact_score <= 100.0

    def test_evidence_records_rule_and_measurement(self):
        result = evaluate_temperature(
            29.0, occupancy=10, capacity=60
        )

        evidence = result.evidence[0]

        assert evidence["rule"] == "temperature_high"
        assert evidence["temperature_c"] == 29.0
        assert evidence["occupancy"] == 10.0
        assert evidence["capacity"] == 60
        assert "occupancy_ratio" in evidence


class TestHumidity:
    def test_inside_band_does_not_fire(self):
        assert (
            evaluate_humidity(50.0, occupancy=10)
            is None
        )

    def test_boundaries_are_inclusive(self):
        """Exactly at a bound is still inside the band."""

        assert (
            evaluate_humidity(HUMIDITY_LOW, occupancy=10)
            is None
        )
        assert (
            evaluate_humidity(HUMIDITY_HIGH, occupancy=10)
            is None
        )

    def test_high_humidity_fires(self):
        result = evaluate_humidity(
            75.0, occupancy=10
        )

        assert result is not None
        assert result.evidence[0]["rule"] == "humidity_high"

    def test_low_humidity_fires(self):
        result = evaluate_humidity(
            20.0, occupancy=10
        )

        assert result.evidence[0]["rule"] == "humidity_low"

    def test_low_is_less_severe_than_high(self):
        low = evaluate_humidity(20.0, occupancy=10)
        high = evaluate_humidity(80.0, occupancy=10)

        assert high.severity == "high"
        assert low.severity == "medium"


class TestCO2:
    def test_below_threshold_does_not_fire(self):
        assert evaluate_co2(CO2_HIGH - 1) is None

    def test_high_fires_with_occupancy_evidence(self):
        result = evaluate_co2(
            1300.0, occupancy=40, capacity=60
        )

        assert result.category == "environment"
        assert result.severity == "high"
        assert result.evidence[0]["co2_ppm"] == 1300.0
        assert result.evidence[0]["occupancy"] == 40.0

    def test_critical_fires(self):
        result = evaluate_co2(CO2_CRITICAL + 100)

        assert result.severity == "critical"
        assert result.impact_score >= 80.0

    def test_fires_without_occupancy_context(self):
        """CO2 is a direct measurement, so it can be judged on
        its own. Suppressing it when occupancy is unknown would
        hide the worst indoor-air failures."""

        result = evaluate_co2(2000.0)

        assert result is not None
        assert "people present" not in result.description


class TestEnergy:
    def test_without_baseline_declines(self):
        assert (
            evaluate_energy(9.0, baseline_kw=None)
            is None
        )

    def test_below_multiplier_does_not_fire(self):
        assert (
            evaluate_energy(
                1.5, baseline_kw=1.0, occupancy=0
            )
            is None
        )

    def test_above_multiplier_fires(self):
        result = evaluate_energy(
            2.0, baseline_kw=1.0, occupancy=0
        )

        assert result.category == "energy"
        assert result.evidence[0]["multiplier"] == 2.0

    def test_absolute_excess_floor_suppresses_noise(self):
        """A 2x jump on a tiny load is noise, not waste."""

        assert (
            evaluate_energy(
                0.4, baseline_kw=0.2, occupancy=0
            )
            is None
        )

    def test_unoccupied_note_is_recorded(self):
        result = evaluate_energy(
            8.5, baseline_kw=1.0, occupancy=0
        )

        assert "no occupants" in (
            result.evidence[0]["note"]
        )

    def test_critical_multiplier(self):
        result = evaluate_energy(
            3.0, baseline_kw=1.0, occupancy=10
        )

        assert result.severity == "critical"
        assert (
            result.evidence[0]["rule"]
            == "energy_critical"
        )


class TestOccupancy:
    def test_at_capacity_does_not_fire(self):
        assert evaluate_occupancy(60.0, capacity=60) is None

    def test_over_capacity_fires(self):
        result = evaluate_occupancy(70.0, capacity=60)

        assert result.category == "occupancy"
        assert result.evidence[0]["capacity"] == 60

    def test_without_capacity_declines(self):
        assert evaluate_occupancy(70.0, capacity=None) is None


class TestDispatch:
    def test_unknown_metric_returns_none(self):
        """A sensor type added later must not break ingestion."""

        assert (
            evaluate_metric("radiation", 5.0, {})
            is None
        )

    def test_known_metric_dispatches(self):
        result = evaluate_metric(
            "co2",
            2000.0,
            {"occupancy": 10, "capacity": 60},
        )

        assert result is not None

    def test_energy_metric_gets_baseline(self):
        result = evaluate_metric(
            "energy",
            8.5,
            {
                "occupancy": 0,
                "capacity": 60,
                "baseline_kw": 1.0,
            },
        )

        assert result is not None

    def test_energy_without_baseline_key_is_safe(self):
        """The dispatcher passes whatever context it was given;
        a missing key must not raise."""

        assert (
            evaluate_metric("energy", 8.5, {}) is None
        )


class TestCategoryConstraints:
    """Every category a rule can emit must satisfy the CHECK
    constraint on incidents.category in PostgreSQL."""

    ALLOWED = {
        "energy",
        "environment",
        "occupancy",
        "water",
        "equipment",
        "safety",
        "maintenance",
        "other",
    }

    ALLOWED_SEVERITY = {
        "low",
        "medium",
        "high",
        "critical",
    }

    @pytest.mark.parametrize(
        "result",
        [
            evaluate_temperature(29.0, occupancy=10),
            evaluate_temperature(33.0, occupancy=10),
            evaluate_humidity(75.0, occupancy=10),
            evaluate_humidity(20.0, occupancy=10),
            evaluate_co2(1300.0, occupancy=10),
            evaluate_co2(2000.0),
            evaluate_energy(3.0, baseline_kw=1.0),
            evaluate_occupancy(80.0, capacity=60),
        ],
    )
    def test_result_satisfies_db_constraints(self, result):
        assert result.category in self.ALLOWED
        assert result.severity in self.ALLOWED_SEVERITY
        assert 0.0 <= result.impact_score <= 100.0
        assert 0.0 <= result.confidence_score <= 100.0
        assert result.evidence
