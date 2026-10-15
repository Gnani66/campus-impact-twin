"""
Deterministic zone physics for the Stage 4 simulator.

NOT a validated building-engineering model. These are
deliberately simple, auditable equations chosen so the demo
produces believable, coupled behaviour: filling the hall
raises CO2 and temperature, ventilation clears CO2, the HVAC
unit pulls temperature back toward setpoint and the energy
meter responds to whatever the HVAC is doing.

Everything here is a pure function of
`(state, controls, dt_seconds, parameters)`. There is no
randomness, no clock read and no I/O, so the same inputs
always give the same output.

Model, per tick of `dt` seconds:

  occupancy  clamped to [0, capacity]
  CO2 (ppm)  + generation from occupancy
              - removal toward outdoor concentration
                proportional to air changes per hour
  temp (°C)  net heat = occupants + solar gain + envelope
              exchange with outdoors - HVAC effect, applied
              against the zone's thermal mass
  RH (%)     + moisture from occupants + infiltration
              - moisture removed by ventilation
  energy(kW) electrical HVAC draw + base load + occupant load

Every constant lives in `SimulationParameters` so it can be
tuned or overridden without editing the equations.
"""

import math
from dataclasses import dataclass, replace
from typing import Dict, Optional


@dataclass(frozen=True)
class SimulationParameters:
    """
    Physical constants for the demo zone.

    Defaults describe LH01: 60 seats, 120 m², served by
    `HVAC-LH01` rated at 12.5 kW.
    """

    zone_capacity: int = 60
    zone_area_sq_m: float = 120.0
    ceiling_height_m: float = 3.0

    # --- CO2 -----------------------------------------------------
    outdoor_co2_ppm: float = 420.0

    # ~25 L of CO2 per person per hour, which is the usual
    # design figure for a sedentary adult. Converted to m³/h.
    co2_generation_l_per_person_hour: float = 25.0

    # Indoor air can never be cleaner than outdoor air, and a
    # sensor this simple is not expected to read above this.
    co2_max_ppm: float = 5000.0

    # --- Temperature --------------------------------------------
    outdoor_temp_c: float = 30.0

    # Sensible heat per occupant. ~70 W for a seated adult in
    # a lecture hall, where most of the person's output is
    # latent and leaves as moisture through the same air.
    occupant_sensible_w: float = 70.0

    # Solar gain per m² of floor at 1000 W/m² irradiance.
    solar_gain_w_per_m2: float = 15.0

    # Conductance of fabric and glazing, W/K.
    envelope_ua_w_per_k: float = 120.0

    # Thermal mass of the air and light structure, J/K.
    # Derived from 120 m² × 3 m × 1.2 kg/m³ × 1005 J/kg/K.
    thermal_capacitance_j_per_k: float = 434_160.0

    # HVAC gain, W/K: the thermal load it takes on per degree
    # of error, capped at rated power / COP. Real air handling
    # moves far more air than this suggests; the number is
    # chosen so the demo reaches setpoint in a sensible number
    # of ticks rather than to represent a plant.
    hvac_ua_w_per_k: float = 1500.0
    hvac_cop: float = 3.0
    hvac_rated_kw: float = 12.5

    # --- Humidity -----------------------------------------------
    # Each occupant raises RH by roughly this much per hour at
    # low ventilation.
    occupant_moisture_pct_per_hour: float = 0.9

    # Ventilation removes this much RH per air change.
    ventilation_humidity_removal_pct_per_ach: float = 3.0

    # Unconditioned air exchange with outside, per hour.
    infiltration_rate_per_hour: float = 0.05

    # --- Energy ---------------------------------------------------
    base_load_kw: float = 0.35
    occupant_load_kw_per_person: float = 0.012

    def replace_zone(
        self,
        capacity: Optional[int] = None,
        area_sq_m: Optional[float] = None,
        hvac_rated_kw: Optional[float] = None,
    ) -> "SimulationParameters":
        """
        Returns a copy with values from the database where
        they are known, so the model follows the real zone
        rather than the defaults above.
        """

        changes = {}

        if capacity is not None:
            changes["zone_capacity"] = int(capacity)

        if area_sq_m is not None:
            changes["zone_area_sq_m"] = float(area_sq_m)

        if hvac_rated_kw is not None:
            changes["hvac_rated_kw"] = float(hvac_rated_kw)

        return replace(self, **changes)


DEFAULT_PARAMETERS = SimulationParameters()


@dataclass(frozen=True)
class SimulationState:
    """The zone at one instant."""

    occupancy: int = 0
    temperature_c: float = 26.0
    humidity_pct: float = 55.0
    co2_ppm: float = 450.0
    energy_kw: float = 0.0


@dataclass(frozen=True)
class SimulationControls:
    """
    Operator inputs for one tick. Nothing here is read from a
    sensor; the simulator decides these from the zone's
    schedule.
    """

    occupancy_target: int = 0
    hvac_enabled: bool = False
    hvac_setpoint_c: float = 22.0
    ventilation_ach: float = 3.0
    outdoor_temp_c: float = 30.0
    outdoor_humidity_pct: float = 55.0
    solar_irradiance_w_m2: float = 0.0


@dataclass(frozen=True)
class SimulationResult:
    """Next state, the readings to publish, and diagnostics."""

    state: SimulationState
    readings: Dict[str, float]
    hvac_thermal_kw: float
    hvac_electrical_kw: float
    ventilation_ach: float


def _clamp(
    value: float,
    low: float,
    high: float,
) -> float:
    return max(low, min(high, value))


def initial_state(
    parameters: SimulationParameters = DEFAULT_PARAMETERS,
) -> SimulationState:
    """
    A plausible unoccupied zone: mild, humid, outdoor CO2.
    """

    return SimulationState(
        occupancy=0,
        temperature_c=max(
            parameters.outdoor_temp_c - 4.0, 15.0
        ),
        humidity_pct=60.0,
        co2_ppm=parameters.outdoor_co2_ppm,
        energy_kw=parameters.base_load_kw,
    )


def step(
    state: SimulationState,
    controls: SimulationControls,
    dt_seconds: float,
    parameters: SimulationParameters = DEFAULT_PARAMETERS,
) -> SimulationResult:
    """
    Advances the zone by `dt_seconds` and returns the next
    state plus one reading per metric.
    """

    if dt_seconds <= 0:
        raise ValueError(
            f"dt_seconds must be positive, got {dt_seconds}"
        )

    dt_hours = dt_seconds / 3600.0

    # --- Occupancy -------------------------------------------------
    occupancy = int(
        _clamp(
            round(controls.occupancy_target),
            0,
            parameters.zone_capacity,
        )
    )

    volume_m3 = (
        parameters.zone_area_sq_m
        * parameters.ceiling_height_m
    )

    ach = max(controls.ventilation_ach, 0.0)

    # --- CO2 -------------------------------------------------------
    # Generated volume adds CO2 at a constant rate; ventilation
    # removes it proportionally to how far the room has drifted
    # above outdoor air. Rates are per second.
    generation_m3_per_s = (
        occupancy
        * parameters.co2_generation_l_per_person_hour
        / 1000.0
        / 3600.0
    )

    generation_ppm_per_s = (
        generation_m3_per_s / volume_m3 * 1_000_000.0
        if volume_m3 > 0
        else 0.0
    )

    decay_per_s = ach / 3600.0

    co2_ppm = state.co2_ppm + dt_seconds * (
        generation_ppm_per_s
        - (state.co2_ppm - parameters.outdoor_co2_ppm)
        * decay_per_s
    )

    # Air can only be as clean as the air outside.
    co2_ppm = _clamp(
        co2_ppm,
        parameters.outdoor_co2_ppm,
        parameters.co2_max_ppm,
    )

    # --- Temperature ----------------------------------------------
    occupant_w = occupancy * parameters.occupant_sensible_w

    solar_w = (
        _clamp(controls.solar_irradiance_w_m2, 0.0, 1000.0)
        * parameters.zone_area_sq_m
        * parameters.solar_gain_w_per_m2
    )

    envelope_w = (
        controls.outdoor_temp_c - state.temperature_c
    ) * parameters.envelope_ua_w_per_k

    # Positive hvac_thermal_kw means heat being removed.
    hvac_thermal_w = 0.0

    if controls.hvac_enabled:
        max_thermal_w = (
            parameters.hvac_rated_kw * 1000.0
        ) / parameters.hvac_cop

        hvac_thermal_w = _clamp(
            (state.temperature_c - controls.hvac_setpoint_c)
            * parameters.hvac_ua_w_per_k,
            -max_thermal_w,
            max_thermal_w,
        )

    net_w = occupant_w + solar_w + envelope_w - hvac_thermal_w

    temperature_c = state.temperature_c + (
        net_w
        * dt_seconds
        / parameters.thermal_capacitance_j_per_k
    )

    temperature_c = _clamp(temperature_c, -10.0, 60.0)

    # --- Humidity --------------------------------------------------
    occupant_moisture_pct_h = (
        occupancy * parameters.occupant_moisture_pct_per_hour
    )

    ventilation_removal_pct_h = (
        ach * parameters.ventilation_humidity_removal_pct_per_ach
    )

    infiltration_pct_h = (
        controls.outdoor_humidity_pct - state.humidity_pct
    ) * parameters.infiltration_rate_per_hour

    humidity_pct = state.humidity_pct + dt_hours * (
        occupant_moisture_pct_h
        - ventilation_removal_pct_h
        + infiltration_pct_h
    )

    humidity_pct = _clamp(humidity_pct, 0.0, 100.0)

    # --- Energy ----------------------------------------------------
    # Electrical draw is the thermal duty divided by COP, so a
    # 12.5 kW unit does not consume 12.5 kW to remove 12.5 kW.
    hvac_electrical_kw = (
        abs(hvac_thermal_w)
        / 1000.0
        / max(parameters.hvac_cop, 1e-6)
    )

    energy_kw = max(
        0.0,
        hvac_electrical_kw
        + parameters.base_load_kw
        + occupancy * parameters.occupant_load_kw_per_person,
    )

    next_state = SimulationState(
        occupancy=occupancy,
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        co2_ppm=co2_ppm,
        energy_kw=energy_kw,
    )

    return SimulationResult(
        state=next_state,
        readings={
            "occupancy": float(occupancy),
            "co2": co2_ppm,
            "temperature": temperature_c,
            "humidity": humidity_pct,
            "energy": energy_kw,
        },
        hvac_thermal_kw=hvac_thermal_w / 1000.0,
        hvac_electrical_kw=hvac_electrical_kw,
        ventilation_ach=ach,
    )