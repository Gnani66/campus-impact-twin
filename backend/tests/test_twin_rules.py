"""
Tests for the digital twin status rules (Phase 12).

The rules are pure, so they can be tested exhaustively without a
database, and they have to be: they decide the colour of a
building in front of a judge.

The tests lean on the case the specification's thresholds get
wrong. Stored occupancy is a headcount; the thresholds are
percentages. Applying one to the other would read 83 people in a
60-seat hall as 83 percent when it is 138 percent, and would
leave every zone under 80 capacity permanently green.
"""

import pytest

from app.core.twin_rules import (
    STATUS_CRITICAL,
    STATUS_NORMAL,
    STATUS_OFFLINE,
    STATUS_WARNING,
    determine_status,
    entity_id_for_code,
    occupancy_ratio,
    status_reasons,
)


# ============================================================
# OCCUPANCY: THE UNIT MISMATCH
# ============================================================


class TestOccupancyRatio:
    def test_ratio(self):
        assert occupancy_ratio(30, 60) == 0.5

    def test_unknown_capacity(self):
        """
        Unknown capacity is different from an empty room, and the
        caller has to be able to tell them apart.
        """

        assert occupancy_ratio(10, None) is None

    def test_zero_capacity_is_undefined(self):
        assert occupancy_ratio(10, 0) is None

    def test_negative_capacity_is_nonsense(self):
        assert occupancy_ratio(10, -5) is None

    def test_negative_headcount_is_refused(self):
        assert occupancy_ratio(-3, 60) is None

    def test_over_capacity_is_allowed(self):
        """
        Over capacity is a real and serious condition, so the
        ratio must be allowed past 1.0 rather than clamped.
        """

        assert occupancy_ratio(83, 60) == pytest.approx(1.3833, abs=1e-3)


class TestOccupancyStatusUsesTheRatio:
    def test_83_people_in_a_60_seat_hall_is_critical(self):
        """
        The specification's own example, under its own
        thresholds. Applied to a headcount this reads 83 percent,
        which is under the 95 limit and would render amber. It is
        138 percent occupancy and is the worst condition in the
        list.
        """

        status = determine_status(
            occupancy_ratio_value=occupancy_ratio(83, 60)
        )

        assert status == STATUS_CRITICAL

    def test_45_people_in_a_60_seat_hall_is_normal(self):
        """
        Three quarters full is not a problem, even though 45 is
        nowhere near a percentage threshold in either direction.
        """

        status = determine_status(
            occupancy_ratio_value=occupancy_ratio(45, 60)
        )

        assert status == STATUS_NORMAL

    def test_80_percent_is_warning(self):
        assert determine_status(
            occupancy_ratio_value=occupancy_ratio(48, 60)
        ) == STATUS_WARNING

    def test_95_percent_is_critical(self):
        assert determine_status(
            occupancy_ratio_value=occupancy_ratio(57, 60)
        ) == STATUS_CRITICAL

    def test_a_small_room_can_still_reach_critical(self):
        """
        With a raw headcount threshold of 95, a twelve-seat study
        room could never trigger a warning no matter how full it
        was. The ratio removes that.
        """

        status = determine_status(
            occupancy_ratio_value=occupancy_ratio(12, 12)
        )

        assert status == STATUS_CRITICAL

    def test_unknown_capacity_does_not_warn(self):
        """
        Without capacity there is no ratio, so occupancy is
        skipped rather than guessed.
        """

        assert determine_status(
            occupancy_ratio_value=occupancy_ratio(200, None)
        ) == STATUS_NORMAL


# ============================================================
# OTHER DIMENSIONS
# ============================================================


class TestStatusRules:
    def test_all_quiet_is_normal(self):
        assert (
            determine_status(
                temperature=22,
                humidity=50,
                aqi=40,
                co2_ppm=600,
                occupancy_ratio_value=0.4,
                sound=55,
            )
            == STATUS_NORMAL
        )

    def test_hot_is_warning(self):
        assert determine_status(temperature=28) == (
            STATUS_WARNING
        )

    def test_very_hot_is_critical(self):
        assert determine_status(temperature=31) == (
            STATUS_CRITICAL
        )

    def test_poor_air_is_warning(self):
        assert determine_status(aqi=150) == STATUS_WARNING

    def test_very_poor_air_is_critical(self):
        assert determine_status(aqi=250) == STATUS_CRITICAL

    def test_stale_co2_is_warning(self):
        """
        1000 ppm is where ventilation is failing rather than
        merely being uncool.
        """

        assert determine_status(co2_ppm=1200) == (
            STATUS_WARNING
        )

    def test_critical_co2_is_critical(self):
        assert determine_status(co2_ppm=1600) == (
            STATUS_CRITICAL
        )

    def test_dry_air_is_warning(self):
        assert determine_status(humidity=30) == (
            STATUS_WARNING
        )

    def test_loud_is_warning(self):
        assert determine_status(sound=75) == STATUS_WARNING

    def test_missing_metrics_are_skipped_not_zero(self):
        """
        A zone with no AQI sensor is not thereby in perfect air
        quality, and a zone with no sound meter is not thereby
        quiet. Unknown is not zero.
        """

        assert (
            determine_status(
                temperature=22,
                aqi=None,
                sound=None,
            )
            == STATUS_NORMAL
        )

    def test_no_data_at_all_is_normal_not_critical(self):
        assert determine_status() == STATUS_NORMAL

    def test_critical_dominates_warning(self):
        """
        The worst dimension decides the colour. A hot room that
        is also dry must not be reported as merely a warning
        because humidity was checked last.
        """

        status = determine_status(
            temperature=31,
            humidity=28,
        )

        assert status == STATUS_CRITICAL

    def test_borders_are_inclusive(self):
        assert determine_status(temperature=27) == (
            STATUS_WARNING
        )
        assert determine_status(temperature=30) == (
            STATUS_CRITICAL
        )


class TestOffline:
    def test_offline_dominates_everything(self):
        """
        A stale reading is not a measurement. Colouring a dead
        sensor green would be the most misleading thing this
        endpoint could do.
        """

        assert determine_status(
            temperature=22,
            offline=True,
        ) == STATUS_OFFLINE

    def test_offline_even_when_values_look_fine(self):
        assert determine_status(
            occupancy_ratio_value=0.1,
            offline=True,
        ) == STATUS_OFFLINE

    def test_offline_overrides_critical_readings(self):
        assert determine_status(
            temperature=45,
            offline=True,
        ) == STATUS_OFFLINE


class TestReasons:
    def test_reason_names_the_dimension(self):
        """
        A marker with a colour and no explanation is decoration.
        """

        reasons = status_reasons(temperature=31)

        assert len(reasons) == 1
        assert "Temperature" in reasons[0]
        assert "31" in reasons[0]

    def test_no_reasons_when_normal(self):
        assert status_reasons(temperature=22) == []

    def test_each_dimension_is_named(self):
        reasons = status_reasons(
            temperature=31,
            humidity=29,
            aqi=250,
            co2_ppm=1600,
            occupancy_ratio_value=1.4,
            sound=90,
        )

        assert len(reasons) == 6

        joined = " ".join(reasons)

        for expected in (
            "Temperature",
            "Humidity",
            "Air quality",
            "CO2",
            "Occupancy",
            "Noise",
        ):
            assert expected in joined


class TestEntityId:
    def test_lecture_hall_code(self):
        assert (
            entity_id_for_code("LH01") == "lecture-hall-01"
        )

    def test_ids_are_distinct(self):
        assert entity_id_for_code("LH01") != (
            entity_id_for_code("LH02")
        )

    def test_lowercase_input(self):
        assert (
            entity_id_for_code("lh01") == "lecture-hall-01"
        )

    def test_laboratory(self):
        assert entity_id_for_code("LAB03").startswith(
            "laboratory"
        )

    def test_unknown_code_is_still_stable(self):
        assert (
            entity_id_for_code("ZZ99")
            == entity_id_for_code("ZZ99")
        )

    def test_empty_code_does_not_crash(self):
        assert entity_id_for_code("") == "unknown"

    def test_no_whitespace(self):
        """
        The id becomes a React key and a URL segment, so it has
        to be safe in both.
        """

        for code in ("LH01", "lab 3", "BUILDING-A"):
            assert " " not in entity_id_for_code(code)
            assert "/" not in entity_id_for_code(code)