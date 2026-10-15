"""
Deterministic physics model tests.

No clock, no randomness, no I/O: same inputs, same outputs.
"""

from dataclasses import replace

import pytest

from app.telemetry.physics import (
    DEFAULT_PARAMETERS,
    SimulationControls,
    SimulationParameters,
    SimulationState,
    initial_state,
    step,
)


PARAMS = DEFAULT_PARAMETERS
DT = 5.0


def run_ticks(
    state: SimulationState,
    controls: SimulationControls,
    ticks: int = 1,
    dt: float = DT,
    parameters: SimulationParameters = PARAMS,
):
    """Advances the model and returns the final state."""

    current = state

    for _ in range(ticks):
        current = step(
            current, controls, dt, parameters
        ).state

    return current


def busy_lectures(**overrides) -> SimulationControls:
    controls = SimulationControls(
        occupancy_target=60,
        hvac_enabled=True,
        hvac_setpoint_c=22.0,
        ventilation_ach=3.0,
        outdoor_temp_c=30.0,
        outdoor_humidity_pct=55.0,
        solar_irradiance_w_m2=400.0,
    )

    return replace(controls, **overrides)


# --- Occupancy bounds ------------------------------------------


@pytest.mark.parametrize(
    "requested,expected",
    [
        (-10, 0),
        (0, 0),
        (1, 1),
        (30, 30),
        (60, 60),
        (61, 60),
        (5_000, 60),
    ],
)
def test_occupancy_is_clamped_to_zone_capacity(
    requested, expected
):
    state = run_ticks(
        initial_state(PARAMS),
        busy_lectures(occupancy_target=requested),
    )

    assert state.occupancy == expected


def test_occupancy_never_negative_over_a_long_run():
    state = run_ticks(
        initial_state(PARAMS),
        busy_lectures(occupancy_target=-100),
        ticks=50,
    )

    assert state.occupancy == 0


# --- CO2 --------------------------------------------------------


def test_co2_rises_with_occupancy_at_constant_ventilation():
    empty = run_ticks(
        initial_state(PARAMS),
        busy_lectures(occupancy_target=0),
        ticks=20,
    )

    full = run_ticks(
        initial_state(PARAMS),
        busy_lectures(occupancy_target=60),
        ticks=20,
    )

    assert full.co2_ppm > empty.co2_ppm
    assert empty.co2_ppm >= PARAMS.outdoor_co2_ppm


def test_co2_increases_monotonically_while_occupied():
    state = initial_state(PARAMS)
    controls = busy_lectures(
        occupancy_target=45, ventilation_ach=0.5
    )

    previous = state.co2_ppm

    for _ in range(10):
        state = step(state, controls, DT, PARAMS).state
        assert state.co2_ppm > previous
        previous = state.co2_ppm


def test_ventilation_lowers_co2_over_time():
    start = initial_state(PARAMS)

    unventilated = run_ticks(
        start,
        busy_lectures(occupancy_target=60, ventilation_ach=0.0),
        ticks=40,
    )

    well_ventilated = run_ticks(
        start,
        busy_lectures(occupancy_target=60, ventilation_ach=12.0),
        ticks=40,
    )

    assert well_ventilated.co2_ppm < unventilated.co2_ppm


def test_ventilation_reduces_an_already_high_co2():
    start = SimulationState(
        occupancy=60,
        temperature_c=28.0,
        humidity_pct=60.0,
        co2_ppm=1800.0,
        energy_kw=4.0,
    )

    # Empty hall, strong ventilation: CO2 must fall.
    after = run_ticks(
        start,
        busy_lectures(occupancy_target=0, ventilation_ach=8.0),
        ticks=60,
    )

    assert after.co2_ppm < start.co2_ppm


def test_co2_never_drops_below_outdoor():
    start = SimulationState(
        occupancy=0,
        temperature_c=26.0,
        humidity_pct=55.0,
        co2_ppm=PARAMS.outdoor_co2_ppm - 200.0,
        energy_kw=0.5,
    )

    after = run_ticks(
        start,
        busy_lectures(occupancy_target=0, ventilation_ach=4.0),
        ticks=5,
    )

    assert after.co2_ppm >= PARAMS.outdoor_co2_ppm


# --- Temperature ------------------------------------------------


def test_temperature_moves_gradually_toward_setpoint():
    """
    One 5s tick must not overshoot the setpoint: the change is
    small, and 15 minutes of HVAC closes most of the gap.
    """

    start = SimulationState(
        occupancy=60,
        temperature_c=30.0,
        humidity_pct=60.0,
        co2_ppm=900.0,
        energy_kw=4.0,
    )

    controls = busy_lectures(
        occupancy_target=20,
        hvac_enabled=True,
        hvac_setpoint_c=22.0,
        outdoor_temp_c=22.0,
        solar_irradiance_w_m2=0.0,
    )

    one_tick = step(start, controls, DT, PARAMS).state

    # Gradual: a single 5s tick barely moves, and it never
    # overshoots the setpoint.
    assert start.temperature_c - one_tick.temperature_c < 1.0
    assert one_tick.temperature_c < start.temperature_c
    assert one_tick.temperature_c > 22.0

    current = start
    previous = current.temperature_c

    # 360 ticks is 30 simulated minutes: the unit runs
    # saturated at first, then settles into proportional control.
    for _ in range(360):
        current = step(current, controls, DT, PARAMS).state
        assert current.temperature_c <= previous
        previous = current.temperature_c

    # Settles close to setpoint, with a small residual because
    # occupant and envelope load is always present.
    assert previous == pytest.approx(22.0, abs=1.2)


def test_hvac_off_lets_temperature_drift_up():
    start = SimulationState(
        occupancy=0,
        temperature_c=22.0,
        humidity_pct=55.0,
        co2_ppm=450.0,
        energy_kw=0.5,
    )

    after = run_ticks(
        start,
        busy_lectures(
            occupancy_target=0,
            hvac_enabled=False,
            outdoor_temp_c=32.0,
            solar_irradiance_w_m2=0.0,
        ),
        ticks=180,
    )

    assert after.temperature_c > 22.0


def test_temperature_is_bounded_under_extremes():
    start = SimulationState(
        occupancy=60,
        temperature_c=55.0,
        humidity_pct=90.0,
        co2_ppm=4000.0,
        energy_kw=8.0,
    )

    after = run_ticks(
        start,
        busy_lectures(
            hvac_enabled=False,
            outdoor_temp_c=60.0,
            solar_irradiance_w_m2=1000.0,
        ),
        ticks=500,
    )

    assert -10.0 <= after.temperature_c <= 60.0


# --- Humidity ---------------------------------------------------


@pytest.mark.parametrize(
    "occupancy,ventilation,outdoor",
    [
        (60, 0.0, 20.0),
        (60, 12.0, 95.0),
        (0, 0.0, 100.0),
        (0, 20.0, 0.0),
    ],
)
def test_humidity_stays_within_bounds(
    occupancy, ventilation, outdoor
):
    state = run_ticks(
        initial_state(PARAMS),
        busy_lectures(
            occupancy_target=occupancy,
            ventilation_ach=ventilation,
            outdoor_humidity_pct=outdoor,
        ),
        ticks=200,
    )

    assert 0.0 <= state.humidity_pct <= 100.0


def test_humidity_rises_with_occupancy_and_low_ventilation():
    start = initial_state(PARAMS)

    empty = run_ticks(
        start,
        busy_lectures(occupancy_target=0, ventilation_ach=1.0),
        ticks=60,
    )

    crowded = run_ticks(
        start,
        busy_lectures(occupancy_target=60, ventilation_ach=0.0),
        ticks=60,
    )

    assert crowded.humidity_pct > empty.humidity_pct


def test_humidity_changes_gradually():
    start = SimulationState(
        occupancy=60,
        temperature_c=26.0,
        humidity_pct=50.0,
        co2_ppm=800.0,
        energy_kw=4.0,
    )

    after = step(
        start,
        busy_lectures(occupancy_target=60, ventilation_ach=1.0),
        DT,
        PARAMS,
    ).state

    assert abs(after.humidity_pct - start.humidity_pct) < 2.0


# --- Energy -----------------------------------------------------


def test_energy_is_never_negative():
    state = run_ticks(
        initial_state(PARAMS),
        busy_lectures(
            occupancy_target=60, hvac_enabled=True
        ),
        ticks=100,
    )

    assert state.energy_kw >= 0.0


def test_energy_is_non_negative_with_hvac_off():
    state = run_ticks(
        initial_state(PARAMS),
        busy_lectures(
            occupancy_target=0, hvac_enabled=False
        ),
        ticks=10,
    )

    assert state.energy_kw >= 0.0
    # Base load plus occupant load only.
    assert state.energy_kw == pytest.approx(
        PARAMS.base_load_kw, abs=0.01
    )


def test_energy_responds_to_hvac_state():
    start = SimulationState(
        occupancy=60,
        temperature_c=30.0,
        humidity_pct=60.0,
        co2_ppm=1200.0,
        energy_kw=5.0,
    )

    cooled = step(
        start,
        busy_lectures(
            occupancy_target=60,
            hvac_enabled=True,
            outdoor_temp_c=30.0,
        ),
        DT,
        PARAMS,
    )

    idle = step(
        start,
        busy_lectures(
            occupancy_target=60,
            hvac_enabled=False,
            outdoor_temp_c=30.0,
        ),
        DT,
        PARAMS,
    )

    assert cooled.state.energy_kw > idle.state.energy_kw
    assert idle.state.energy_kw == pytest.approx(
        PARAMS.base_load_kw
        + 60 * PARAMS.occupant_load_kw_per_person,
        abs=1e-6,
    )


def test_energy_stays_within_the_hvac_reference():
    """
    The HVAC cannot draw more than its 12.5 kW rating, and
    electrical draw is the thermal duty over COP.
    """

    start = SimulationState(
        occupancy=60,
        temperature_c=60.0,
        humidity_pct=60.0,
        co2_ppm=2000.0,
        energy_kw=0.0,
    )

    result = step(
        start,
        busy_lectures(
            occupancy_target=60,
            hvac_enabled=True,
            hvac_setpoint_c=10.0,
            outdoor_temp_c=60.0,
            solar_irradiance_w_m2=1000.0,
        ),
        DT,
        PARAMS,
    )

    # Saturated cooling: the unit runs at its rated limit.
    assert result.hvac_thermal_kw == pytest.approx(
        PARAMS.hvac_rated_kw / PARAMS.hvac_cop,
        rel=1e-6,
    )
    assert result.hvac_electrical_kw <= PARAMS.hvac_rated_kw
    assert result.state.energy_kw <= PARAMS.hvac_rated_kw


def test_energy_rises_with_occupancy():
    start = initial_state(PARAMS)

    empty = run_ticks(
        start,
        busy_lectures(
            occupancy_target=0,
            hvac_enabled=False,
            ventilation_ach=6.0,
        ),
        ticks=5,
    )

    crowded = run_ticks(
        start,
        busy_lectures(
            occupancy_target=60,
            hvac_enabled=False,
            ventilation_ach=6.0,
        ),
        ticks=5,
    )

    assert crowded.energy_kw > empty.energy_kw


# --- Determinism and contract ----------------------------------


def test_same_inputs_produce_identical_results():
    start = initial_state(PARAMS)
    controls = busy_lectures(occupancy_target=42)

    first = run_ticks(start, controls, ticks=25)
    second = run_ticks(start, controls, ticks=25)

    assert first == second


def test_step_rejects_non_positive_dt():
    with pytest.raises(ValueError):
        step(
            initial_state(PARAMS),
            busy_lectures(),
            0.0,
            PARAMS,
        )

    with pytest.raises(ValueError):
        step(
            initial_state(PARAMS),
            busy_lectures(),
            -1.0,
            PARAMS,
        )


def test_result_exposes_one_reading_per_seeded_metric():
    result = step(
        initial_state(PARAMS),
        busy_lectures(),
        DT,
        PARAMS,
    )

    assert set(result.readings) == {
        "co2",
        "energy",
        "humidity",
        "occupancy",
        "temperature",
    }
    assert result.readings["occupancy"] == 60.0


def test_replace_zone_uses_database_values():
    params = PARAMS.replace_zone(
        capacity=40,
        area_sq_m=80.0,
        hvac_rated_kw=9.0,
    )

    assert params.zone_capacity == 40
    assert params.zone_area_sq_m == 80.0
    assert params.hvac_rated_kw == 9.0

    # Original defaults untouched.
    assert PARAMS.zone_capacity == 60


def test_zone_capacity_from_database_is_respected():
    """
    A capacity read from the database overrides the default,
    so a smaller zone is capped correctly.
    """

    params = PARAMS.replace_zone(capacity=30)

    state = run_ticks(
        initial_state(params),
        busy_lectures(occupancy_target=55),
        ticks=1,
        parameters=params,
    )

    assert state.occupancy == 30