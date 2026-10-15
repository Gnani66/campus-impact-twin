#!/usr/bin/env python
"""
Smart Campus Sensor Simulator — standalone publisher.

Publishes one reading per registered sensor to the MQTT broker
on a fixed interval, so the FastAPI worker can ingest it and
write it to Supabase.

Usage
-----
    python simulator.py
    python simulator.py --ticks 20
    python simulator.py --fault hvac-stuck-on
    python simulator.py --fault hvac-stuck-on \\
        --fault-after-ticks 24 --fault-ticks 60

The loop drives `TelemetrySimulator.build_tick()` and
`publish_tick()` directly rather than `run()`, so each tick can
be printed and a fault schedule can be applied.

MQTT_ENABLED is deliberately not required here. That flag exists
so the API never starts a simulator on its own; this script is an
explicit request for one. MQTT_HOST and MQTT_PORT are still read
from settings.
"""

import argparse
import asyncio
import logging
import signal
import sys
from dataclasses import (
    dataclass,
    field,
    replace,
)
from datetime import datetime
from typing import (
    Callable,
    Dict,
    List,
    Optional,
)

from app.core.config import settings
from app.telemetry.physics import SimulationControls
from app.telemetry.registry import get_registry
from app.telemetry.simulator import (
    ScheduleControlsProvider,
    SimulatorError,
    TelemetrySimulator,
    encode_payload,
)

logger = logging.getLogger("simulator")


# ============================================================
# FAULT INJECTION
#
# Faults are applied to the *controls* the simulator feeds into
# the physics, not to the produced readings. That matters: the
# readings then follow from the fault through the same
# equations as normal operation, so the data stays internally
# consistent. An anomaly detector should not be able to tell a
# fault from reality by looking at physical plausibility alone.
# ============================================================


@dataclass(frozen=True)
class FaultPlan:
    mode: str
    start_tick: int
    duration_ticks: int


FAULT_MODES = {
    "hvac-stuck-on": (
        "HVAC runs outside occupied hours. Signature: a step "
        "change in energy (roughly 0.35 -> 1.7 kW at zero "
        "occupancy) with temperature actively falling. "
        "Detectable within a tick."
    ),
    "no-ventilation": (
        "Ventilation is throttled while the hall is full. "
        "Signature: CO2 diverges upward from the healthy "
        "trajectory. This is a drift, not a step: at ~55 "
        "occupants the gap reaches roughly +100 ppm after 20 "
        "minutes and +300 ppm after 40. Needs trend detection, "
        "not a threshold."
    ),
    "overcool": (
        "HVAC setpoint is forced to 16 C. Signature: energy "
        "sits at maximum draw and temperature falls "
        "steadily regardless of outdoor conditions."
    ),
    "door-left-open": (
        "HVAC is disabled while the hall is full. Signature: "
        "temperature drifts toward outdoor while occupancy "
        "stays high, and energy collapses to base load."
    ),
}


DEMO_SCENARIO = {
    "occupancy": 58.0,
    "temperature": 30.5,
    "humidity": 72.0,
    "co2": 1850.0,
    "energy": 8.5,
}


@dataclass(frozen=True)
class DemoScenario:
    """
    A scripted abnormal period, applied on top of the physics.

    The Phase 6 spec sets scripted values directly on the
    generated state. That is not possible here, because this
    simulator has no state dictionary: it advances a continuous
    physical model and derives readings from it. The scripted
    values are therefore applied to the *readings* after the tick
    is built.

    The trade-off is explicit. Readings inside the window are no
    longer physically consistent with the model that produced the
    surrounding healthy data, so they must be read as a scripted
    demonstration rather than as simulated reality. That is why
    this is opt-in via `--scenario demo` and never the default.

    Applying at the reading level is also what makes the demo work
    outside opening hours. The zone schedule forces occupancy to
    zero after 18:00, so a controls-level scenario would never
    produce the 58 people the CO2 and over-capacity rules need.
    """

    normal_ticks: int = 20
    event_ticks: int = 15
    values: Dict[str, float] = field(
        default_factory=lambda: dict(DEMO_SCENARIO)
    )

    @property
    def cycle(self) -> int:
        return self.normal_ticks + self.event_ticks

    def is_event(self, tick: int) -> bool:
        return (
            self.normal_ticks
            <= tick % self.cycle
            < self.normal_ticks + self.event_ticks
        )

    def apply(
        self,
        readings: List,
        tick: int,
    ) -> List:
        """
        Overrides the readings produced by the physics for the
        duration of the scripted event.
        """

        if not self.is_event(tick):
            return readings

        for reading in readings:
            override = self.values.get(
                reading.message.metric
            )

            if override is None:
                continue

            message = reading.message.model_copy(
                update={
                    "value": override,
                    "metadata": {
                        **reading.message.metadata,
                        "demo_scenario": True,
                        "scripted": True,
                    },
                }
            )

            reading.message = message
            reading.payload = encode_payload(message)

        return readings


class OccupancyOverride:
    """
    Forces a headcount regardless of the zone schedule.

    The seeded LH01 schedule is 08:00-18:00 local, so outside
    those hours the real schedule pins occupancy to zero and
    every signal flattens to base load. Without this, history
    generated overnight is degenerate: no occupancy variance,
    no CO2 build-up, nothing for Phase 6 to detect.
    """

    def __init__(
        self,
        base: Callable,
        count: int,
    ) -> None:
        self._base = base
        self._count = max(int(count), 0)

    def __call__(
        self,
        when: datetime,
        entry,
    ) -> SimulationControls:
        controls = self._base(when, entry)

        return replace(
            controls,
            occupancy_target=self._count,
        )


class FaultInjector:
    """
    Wraps a controls provider and overrides it during a window.

    The caller advances the schedule with `begin_tick` before
    each `build_tick`, because the simulator invokes the
    provider as `provider(timestamp, entry)` and does not pass
    a tick number.
    """

    def __init__(
        self,
        base: Callable,
        plan: Optional[FaultPlan],
    ) -> None:
        self._base = base
        self._plan = plan
        self._tick = 0
        self.active = False

    def begin_tick(self, tick: int) -> None:
        self._tick = tick

    def _should_apply(self) -> bool:
        if self._plan is None:
            return False

        return (
            self._plan.start_tick
            <= self._tick
            < self._plan.start_tick + self._plan.duration_ticks
        )

    def _apply(
        self,
        controls: SimulationControls,
    ) -> SimulationControls:
        mode = self._plan.mode

        if mode == "hvac-stuck-on":
            return replace(
                controls,
                hvac_enabled=True,
            )

        if mode == "no-ventilation":
            return replace(
                controls,
                ventilation_ach=0.5,
            )

        if mode == "overcool":
            return replace(
                controls,
                hvac_enabled=True,
                hvac_setpoint_c=16.0,
            )

        if mode == "door-left-open":
            return replace(
                controls,
                hvac_enabled=False,
            )

        return controls

    def __call__(
        self,
        when: datetime,
        entry,
    ) -> SimulationControls:
        controls = self._base(when, entry)

        self.active = self._should_apply()

        if not self.active:
            return controls

        return self._apply(controls)


# ============================================================
# CONSOLE OUTPUT
# ============================================================


def describe_tick(
    readings: List,
    registry,
    tick: int,
) -> str:
    parts = [
        f"{code_for(registry, r)}="
        f"{r.message.value:.2f}{r.message.unit}"
        for r in readings
    ]

    return f"[tick {tick:>5}] " + "  ".join(parts)


def code_for(registry, reading) -> str:
    """
    Sensor code for a reading. The payload carries the sensor
    UUID, the operator-facing name is the code.
    """

    entry = registry.get_by_id(
        reading.message.sensor_id
    )

    return (
        entry.sensor_code
        if entry is not None
        else str(reading.message.sensor_id)
    )


# ============================================================
# MAIN LOOP
# ============================================================


async def run(args: argparse.Namespace) -> int:
    import aiomqtt

    interval = float(args.interval)

    # The registry loads through a synchronous Supabase client,
    # so it must not block the event loop.
    loop = asyncio.get_running_loop()

    try:
        registry = await loop.run_in_executor(
            None, get_registry
        )
    except Exception as exc:
        print(
            f"  ABORT: could not load the sensor registry: "
            f"{exc}",
            file=sys.stderr,
        )
        print(
            "         Check SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in backend/.env",
            file=sys.stderr,
        )
        return 2

    # The simulator resolves zone capacity, floor and schedule
    # from the temperature sensor's registry entry, so the
    # controls provider is built from the same entry.
    zone_entry = next(
        entry
        for entry in registry
        if entry.metric == "temperature"
    )

    plan: Optional[FaultPlan] = None

    if args.fault != "none":
        plan = FaultPlan(
            mode=args.fault,
            start_tick=args.fault_after_ticks,
            duration_ticks=args.fault_ticks,
        )

    schedule = ScheduleControlsProvider(
        capacity=zone_entry.zone_capacity,
        start_hour=zone_entry.zone_schedule_start_hour,
        end_hour=zone_entry.zone_schedule_end_hour,
    )

    controls_provider: Callable = schedule

    if args.occupancy is not None:
        controls_provider = OccupancyOverride(
            controls_provider,
            args.occupancy,
        )

    controls_provider = FaultInjector(
        controls_provider, plan
    )

    scenario: Optional[DemoScenario] = None

    if args.scenario == "demo":
        scenario = DemoScenario()

    client = aiomqtt.Client(
        hostname=settings.mqtt_host,
        port=settings.mqtt_port,
    )

    simulator = TelemetrySimulator(
        registry=registry,
        client=client,
        controls_provider=controls_provider,
    )

    codes = ", ".join(sorted(registry.sensor_codes))

    print("Smart Campus Sensor Simulator")
    print(
        f"MQTT broker: {settings.mqtt_host}:"
        f"{settings.mqtt_port}"
    )
    print(
        f"Publishing every {interval:.0f} seconds..."
    )
    print(f"Sensors ({len(registry)}): {codes}")

    if args.occupancy is not None:
        print(
            f"Occupancy: forced to {args.occupancy} people "
            f"(schedule {zone_entry.zone_schedule_start_hour}"
            f":00-{zone_entry.zone_schedule_end_hour}:00 "
            f"bypassed)"
        )

    if scenario is not None:
        print(
            "Demo scenario: NORMAL for "
            f"{scenario.normal_ticks} ticks, then "
            f"58 people / 30.5 C / 72% / 1850 ppm / 8.5 kW "
            f"for {scenario.event_ticks} ticks, then NORMAL "
            f"(repeats every {scenario.cycle} ticks)"
        )

    if plan is not None:
        print(
            f"Fault '{plan.mode}' scheduled from tick "
            f"{plan.start_tick} for {plan.duration_ticks} "
            f"ticks"
        )
        print(f"  {FAULT_MODES[plan.mode]}")
    else:
        print("Faults: none (healthy operation only)")

    print("")

    stopping = asyncio.Event()

    loop.add_signal_handler(
        signal.SIGINT, stopping.set
    )
    loop.add_signal_handler(signal.SIGTERM, stopping.set)

    tick = 0
    published = 0

    try:
        async with client:
            print("[MQTT] Connected to broker.")

            while not stopping.is_set():
                if (
                    args.ticks is not None
                    and tick >= args.ticks
                ):
                    break

                tick += 1

                if (
                    plan is not None
                    and tick == plan.start_tick
                ):
                    print(
                        f"[tick {tick:>5}] *** FAULT "
                        f"'{plan.mode}' INJECTED ***"
                    )

                if (
                    plan is not None
                    and tick
                    == plan.start_tick
                    + plan.duration_ticks
                ):
                    print(
                        f"[tick {tick:>5}] *** fault cleared "
                        f"***"
                    )

                controls_provider.begin_tick(tick)

                readings = simulator.build_tick()

                if scenario is not None:
                    readings = scenario.apply(
                        readings, tick
                    )

                await simulator.publish_tick(readings)

                published += len(readings)

                if scenario is not None and (
                    tick == scenario.normal_ticks + 1
                    or tick == 1
                ):
                    if scenario.is_event(tick):
                        print(
                            f"[tick {tick:>5}] *** DEMO SCENARIO "
                            f"START: sustained abnormal conditions "
                            f"for {scenario.event_ticks} ticks ***"
                        )
                    else:
                        print(
                            f"[tick {tick:>5}] DEMO SCENARIO armed: "
                            f"starts at tick {scenario.normal_ticks + 1}"
                        )

                if args.verbose:
                    for reading in readings:
                        print(
                            f"[MQTT] {code_for(registry, reading)}"
                            f": {reading.message.value:.2f} "
                            f"{reading.message.unit}"
                        )
                elif tick % args.every == 0 or tick == 1:
                    print(
                        describe_tick(
                            readings, registry, tick
                        )
                    )

                await asyncio.sleep(interval)

    except asyncio.CancelledError:
        pass
    except (OSError, aiomqtt.ClientError) as exc:
        print("", file=sys.stderr)
        print(
            f"[MQTT] Broker connection failed: {exc}",
            file=sys.stderr,
        )
        print(
            "       Start it from the repo root with:",
            file=sys.stderr,
        )
        print("       docker compose up -d", file=sys.stderr)
        return 3

    print("")
    print(
        f"Stopped after {tick} ticks, "
        f"{published} readings published."
    )

    return 0


def parse_args(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        description=(
            "Publish simulated campus telemetry to the MQTT "
            "broker."
        )
    )

    parser.add_argument(
        "--ticks",
        type=int,
        default=None,
        help="stop after this many ticks (default: run "
        "until Ctrl+C)",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=float(
            settings.telemetry_tick_seconds
        ),
        help="seconds between ticks",
    )

    parser.add_argument(
        "--every",
        type=int,
        default=1,
        help="print every Nth tick",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print one line per sensor per tick",
    )

    parser.add_argument(
        "--occupancy",
        type=int,
        default=None,
        help=(
            "force a headcount instead of following the zone "
            "schedule. Use this to generate history outside "
            "opening hours; without it every tick after 18:00 "
            "is unoccupied and flat. (default: follow "
            "schedule)"
        ),
    )

    parser.add_argument(
        "--scenario",
        choices=["none", "demo"],
        default="none",
        help=(
            "'demo' scripts a sustained abnormal window so the "
            "intelligence engine has something to detect "
            "(default: none)"
        ),
    )

    parser.add_argument(
        "--fault",
        choices=["none", *sorted(FAULT_MODES)],
        default="none",
        help="fault to inject (default: none)",
    )

    parser.add_argument(
        "--fault-after-ticks",
        type=int,
        default=24,
        help="tick at which the fault starts (default: 24)",
    )

    parser.add_argument(
        "--fault-ticks",
        type=int,
        default=60,
        help="how many ticks the fault lasts (default: 60)",
    )

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        return asyncio.run(run(args))
    except SimulatorError as exc:
        print(f"  ABORT: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
