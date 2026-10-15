"""
MQTT telemetry simulator.

Advances the zone physics one tick at a time and publishes one
reading per registered sensor to the broker. MQTT publishing
is its only output: nothing here writes to Supabase.

Lifecycle:

    simulator = TelemetrySimulator(registry=get_registry())
    await simulator.run()          # connects, publishes, stops on cancel

    task = simulator.start()       # background task
    await simulator.stop()

`settings.mqtt_enabled` gates everything. When it is false the
simulator logs and returns without connecting, so importing
this module can never open a socket.

Readings are marked `source="simulator"` and carry
`metadata.simulated = true`. They are demo values from the
model in `app.telemetry.physics`, not measurements.
"""

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import (
    Callable,
    List,
    Optional,
    Sequence,
)

from app.core.config import settings
from app.telemetry.models import (
    SEED_METRIC_UNITS,
    TelemetryMessage,
)
from app.telemetry.physics import (
    DEFAULT_PARAMETERS,
    SimulationControls,
    SimulationParameters,
    SimulationState,
    initial_state,
    step,
)
from app.telemetry.registry import SensorEntry, SensorRegistry
from app.telemetry.topics import build_topic


logger = logging.getLogger(__name__)


class SimulatorError(RuntimeError):
    """
    Raised when the simulator cannot run: no broker enabled,
    or a registry that does not describe the seeded sensors.
    """


# Metrics the simulator is expected to produce, from the five
# seeded sensors. Nothing else is invented here.
EXPECTED_METRICS = frozenset(SEED_METRIC_UNITS)

REQUIRED_ENTRY_FIELDS = (
    "sensor_id",
    "sensor_code",
    "sensor_type",
    "unit",
    "campus_code",
    "building_code",
    "floor_code",
    "zone_code",
)


class PublishedReading:
    """One topic plus the compact JSON body for it."""

    __slots__ = ("topic", "payload", "message")

    def __init__(
        self,
        topic: str,
        payload: str,
        message: TelemetryMessage,
    ) -> None:
        self.topic = topic
        self.payload = payload
        self.message = message

    def __repr__(self) -> str:
        return (
            f"PublishedReading(topic={self.topic!r}, "
            f"metric={self.message.metric!r}, "
            f"value={self.message.value!r})"
        )


def encode_payload(message: TelemetryMessage) -> str:
    """
    Compact JSON for one reading.

    `mode="json"` renders UUIDs as strings and the timestamp as
    ISO-8601, which is exactly what `TelemetryMessage(**body)`
    expects on the receiving side.
    """

    return json.dumps(
        message.model_dump(mode="json"),
        separators=(",", ":"),
    )


class ScheduleControlsProvider:
    """
    Derives controls from the zone's own schedule.

    Reads `schedule_start_hour` / `schedule_end_hour` from the
    database where present and falls back to the seeded LH01
    values (08:00–18:00, Monday–Saturday). Occupancy ramps in
    over the first quarter hour and out over the last, which
    is a demo convention, not a real attendance pattern.
    """

    RAMP_MINUTES = 15.0

    def __init__(
        self,
        capacity: int,
        start_hour: Optional[int] = None,
        end_hour: Optional[int] = None,
        active_days: Sequence[int] = (1, 2, 3, 4, 5, 6),
        hvac_setpoint_c: float = 22.0,
    ) -> None:
        self.capacity = max(int(capacity), 0)
        self.start_hour = (
            8 if start_hour is None else int(start_hour)
        )
        self.end_hour = (
            18 if end_hour is None else int(end_hour)
        )
        self.active_days = tuple(active_days)
        self.hvac_setpoint_c = hvac_setpoint_c

    def occupancy_at(
        self,
        when: datetime,
    ) -> int:
        local = when.astimezone()

        if local.isoweekday() not in self.active_days:
            return 0

        hour = local.hour

        if hour < self.start_hour or hour >= self.end_hour:
            return 0

        minutes_since_open = (
            hour - self.start_hour
        ) * 60 + local.minute

        minutes_to_close = (
            self.end_hour - hour
        ) * 60 - local.minute

        if minutes_since_open < self.RAMP_MINUTES:
            fraction = minutes_since_open / self.RAMP_MINUTES
        elif minutes_to_close < self.RAMP_MINUTES:
            fraction = max(
                minutes_to_close / self.RAMP_MINUTES, 0.0
            )
        else:
            fraction = 1.0

        return int(
            round(self.capacity * min(max(fraction, 0.0), 1.0))
        )

    def __call__(
        self,
        when: datetime,
        entry: SensorEntry,
    ) -> SimulationControls:
        occupancy = self.occupancy_at(when)
        local_hour = when.astimezone().hour + (
            when.astimezone().minute / 60.0
        )

        # Simple diurnal curves, deterministic for a given
        # clock time. A real demo would feed weather here.
        outdoor_temp_c = 26.0 + 4.0 * math.sin(
            (local_hour - 9.0) / 24.0 * 6.283185307179586
        )
        outdoor_humidity_pct = 60.0 - 10.0 * math.sin(
            (local_hour - 9.0) / 24.0 * 6.283185307179586
        )
        solar_irradiance_w_m2 = max(
            0.0,
            math.sin(
                (local_hour - 6.0) / 12.0 * 3.141592653589793
            )
            * 800.0,
        )

        # Ventilation tracks occupancy: an empty hall is not
        # mechanically ventilated at full rate.
        ventilation_ach = (
            1.0
            if occupancy == 0
            else 2.0 + 2.0 * (occupancy / max(self.capacity, 1))
        )

        hvac_enabled = occupancy > 0 or (
            self.start_hour
            <= when.astimezone().hour
            < self.end_hour
        )

        return SimulationControls(
            occupancy_target=occupancy,
            hvac_enabled=hvac_enabled,
            hvac_setpoint_c=self.hvac_setpoint_c,
            ventilation_ach=ventilation_ach,
            outdoor_temp_c=outdoor_temp_c,
            outdoor_humidity_pct=outdoor_humidity_pct,
            solar_irradiance_w_m2=solar_irradiance_w_m2,
        )


class TelemetrySimulator:
    """
    Publishes simulated readings for every registered sensor.
    """

    def __init__(
        self,
        registry: SensorRegistry,
        client: object = None,
        app_settings: object = None,
        clock: Optional[Callable[[], datetime]] = None,
        controls_provider: Optional[Callable] = None,
        parameters: SimulationParameters = None,
    ) -> None:
        if registry is None:
            raise SimulatorError(
                "a SensorRegistry is required; build it with "
                "app.telemetry.registry.get_registry() off the "
                "event loop"
            )

        self._settings = (
            app_settings if app_settings is not None else settings
        )
        self._registry = registry
        self._client = client
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._parameters = parameters or DEFAULT_PARAMETERS

        self._validate_registry()

        entry = self._entry_for_metric("temperature")

        if controls_provider is None:
            controls_provider = ScheduleControlsProvider(
                capacity=(
                    entry.zone_capacity
                    or self._parameters.zone_capacity
                ),
                start_hour=entry.zone_schedule_start_hour,
                end_hour=entry.zone_schedule_end_hour,
            )

        self._controls_provider = controls_provider

        self._state = initial_state(
            self._resolved_parameters(entry)
        )
        self._task: Optional[asyncio.Task] = None

    # --- setup helpers -----------------------------------------

    @property
    def state(self) -> SimulationState:
        return self._state

    @property
    def registry(self) -> SensorRegistry:
        return self._registry

    def _validate_registry(self) -> None:
        """
        Fails loudly rather than publishing a partial tick.
        """

        problems: List[str] = []

        for entry in self._registry:
            for name in REQUIRED_ENTRY_FIELDS:
                value = getattr(entry, name, None)

                if value is None or value == "":
                    problems.append(
                        f"{entry.sensor_code or '?'}: "
                        f"missing {name}"
                    )

            metric = entry.metric

            if metric not in SEED_METRIC_UNITS:
                problems.append(
                    f"{entry.sensor_code}: unsupported "
                    f"metric '{metric}'"
                )
            elif entry.unit not in SEED_METRIC_UNITS[metric]:
                problems.append(
                    f"{entry.sensor_code}: unit "
                    f"'{entry.unit}' is not valid for "
                    f"'{metric}'"
                )

        missing = EXPECTED_METRICS - {
            entry.metric for entry in self._registry
        }

        if missing:
            problems.append(
                "registry is missing metrics "
                f"{sorted(missing)}"
            )

        if problems:
            raise SimulatorError(
                "registry is not usable for simulation: "
                + "; ".join(problems)
            )

    def _entry_for_metric(
        self, metric: str
    ) -> SensorEntry:
        for entry in self._registry:
            if entry.metric == metric:
                return entry

        raise SimulatorError(
            f"no sensor registered for metric '{metric}'"
        )

    def _resolved_parameters(
        self, entry: SensorEntry
    ) -> SimulationParameters:
        return self._parameters.replace_zone(
            capacity=entry.zone_capacity,
            area_sq_m=entry.zone_area_sq_meters,
            hvac_rated_kw=entry.equipment_rated_power_kw,
        )

    # --- tick -----------------------------------------------------

    def build_tick(
        self,
        now: Optional[datetime] = None,
        dt_seconds: Optional[float] = None,
    ) -> List[PublishedReading]:
        """
        Advances the model one tick and returns the readings to
        publish. Pure with respect to MQTT: nothing is sent
        here, which keeps the tick testable offline.
        """

        timestamp = now or self._clock()

        if timestamp.tzinfo is None:
            raise SimulatorError(
                "simulator clock must return a "
                "timezone-aware datetime"
            )

        interval = (
            float(self._settings.telemetry_tick_seconds)
            if dt_seconds is None
            else float(dt_seconds)
        )

        zone_entry = self._entry_for_metric("temperature")
        controls = self._controls_provider(
            timestamp, zone_entry
        )

        result = step(
            self._state,
            controls,
            interval,
            self._resolved_parameters(zone_entry),
        )

        self._state = result.state

        readings = []

        for entry in self._registry:
            message = TelemetryMessage(
                sensor_id=entry.sensor_id,
                metric=entry.metric,
                value=result.readings[entry.metric],
                unit=entry.unit,
                timestamp=timestamp,
                source="simulator",
                quality="good",
                campus_id=entry.campus_id,
                building_id=entry.building_id,
                floor_id=entry.floor_id,
                zone_id=entry.zone_id,
                equipment_id=entry.equipment_id,
                metadata={
                    "simulated": True,
                    "model": "stage4-deterministic-demo",
                },
            )

            readings.append(
                PublishedReading(
                    topic=build_topic(
                        entry,
                        prefix=self._settings.mqtt_topic_prefix,
                    ),
                    payload=encode_payload(message),
                    message=message,
                )
            )

        return readings

    async def publish_tick(
        self,
        readings: Sequence[PublishedReading],
    ) -> None:
        """
        Publishes one tick's readings to the broker.
        """

        client = self._require_client()

        for reading in readings:
            await client.publish(
                reading.topic,
                reading.payload.encode("utf-8"),
                qos=0,
            )

    def _require_client(self) -> object:
        if self._client is None:
            self._client = self._build_client()

        return self._client

    def _build_client(self) -> object:
        import aiomqtt

        return aiomqtt.Client(
            hostname=self._settings.mqtt_host,
            port=self._settings.mqtt_port,
        )

    # --- lifecycle -----------------------------------------------

    def start(self) -> Optional[asyncio.Task]:
        """
        Starts the publish loop as a background task.

        Returns None when MQTT is disabled, so nothing
        connects. Not called at import time.
        """

        if not self._settings.mqtt_enabled:
            logger.info(
                "Telemetry simulator disabled "
                "(MQTT_ENABLED=false); not connecting"
            )
            return None

        if self._task is not None and not self._task.done():
            return self._task

        self._task = asyncio.create_task(
            self.run(), name="telemetry-simulator"
        )

        return self._task

    async def stop(self) -> None:
        """
        Cancels the publish loop and waits for the client to
        disconnect.
        """

        task = self._task
        self._task = None

        if task is None:
            return

        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

    async def __aenter__(self) -> "TelemetrySimulator":
        self.start()
        return self

    async def __aexit__(self, *_exc_info) -> None:
        await self.stop()

    async def run(
        self,
        max_ticks: Optional[int] = None,
    ) -> None:
        """
        Connects, publishes a tick, and repeats until
        cancelled.

        `max_ticks` exists for tests and short demos; it is
        None in normal operation.
        """

        if not self._settings.mqtt_enabled:
            logger.info(
                "Telemetry simulator disabled "
                "(MQTT_ENABLED=false); not connecting"
            )
            return

        interval = float(
            self._settings.telemetry_tick_seconds
        )
        client = self._require_client()

        ticks = 0

        # Entering the client context connects and, crucially,
        # disconnects on the way out including on cancellation.
        async with client:
            logger.info(
                "Telemetry simulator connected to %s:%s, "
                "publishing %d sensors every %.0fs",
                self._settings.mqtt_host,
                self._settings.mqtt_port,
                len(self._registry),
                interval,
            )

            try:
                while max_ticks is None or ticks < max_ticks:
                    readings = self.build_tick()
                    await self.publish_tick(readings)

                    ticks += 1

                    logger.debug(
                        "tick %d published: %s",
                        ticks,
                        ", ".join(
                            f"{r.message.metric}="
                            f"{r.message.value:.2f}"
                            for r in readings
                        ),
                    )

                    if (
                        max_ticks is not None
                        and ticks >= max_ticks
                    ):
                        break

                    await asyncio.sleep(interval)

            except asyncio.CancelledError:
                logger.info(
                    "Telemetry simulator cancelled after "
                    "%d ticks; disconnecting",
                    ticks,
                )
                raise

        logger.info(
            "Telemetry simulator stopped after %d ticks",
            ticks,
        )