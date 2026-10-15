"""
Simulator tests.

Fully offline: a fake MQTT client records published messages
instead of opening a socket, and the registry is the same fake
the Stage 3 tests use. No broker, no Supabase, no network.

Async behaviour is exercised with `asyncio.run` so no
pytest-asyncio or other plugin is needed.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.telemetry.models import TelemetryMessage
from app.telemetry.physics import (
    SimulationControls,
    SimulationParameters,
    SimulationState,
)
from app.telemetry.registry import (
    SensorEntry,
    SensorRegistry,
    UnknownSensorError,
)
from app.telemetry.simulator import (
    ScheduleControlsProvider,
    SimulatorError,
    TelemetrySimulator,
    encode_payload,
)
from app.telemetry.topics import parse_topic


from conftest import SEED_IDS, make_entry


TICK_AT = datetime(2026, 3, 3, 11, 0, tzinfo=timezone.utc)


@dataclass
class FakeSettings:
    """Only the attributes the simulator reads."""

    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "smart-campus"
    telemetry_tick_seconds: int = 5
    telemetry_flush_seconds: int = 10


class FakeMqttClient:
    """
    Records publishes and tracks connection lifecycle, matching
    the async context manager protocol aiomqtt.Client uses.
    """

    def __init__(self) -> None:
        self.published = []
        self.entered = 0
        self.exited = 0
        self.publish_error: Exception = None

    async def __aenter__(self) -> "FakeMqttClient":
        self.entered += 1
        return self

    async def __aexit__(self, *_exc_info) -> None:
        self.exited += 1

    async def publish(
        self, topic, payload, qos=0, retain=False
    ) -> None:
        if self.publish_error is not None:
            raise self.publish_error

        self.published.append((topic, payload, qos))


def make_entries(**overrides):
    """
    The five seeded sensors, optionally with attribute
    overrides applied to every entry.
    """

    entries = [
        make_entry("CO2-LH01", "co2", "ppm"),
        make_entry("ENERGY-LH01", "energy", "kW"),
        make_entry("HUM-LH01", "humidity", "%"),
        make_entry("OCC-LH01", "occupancy", "people"),
        make_entry("TEMP-LH01", "temperature", "°C"),
    ]

    if not overrides:
        return entries

    return [
        SensorEntry(
            **{
                **entry.__dict__,
                **{
                    key: value
                    for key, value in overrides.items()
                    if value is not None
                    or key
                    in {
                        "zone_capacity",
                        "zone_area_sq_meters",
                    }
                },
            }
        )
        for entry in entries
    ]


@pytest.fixture
def registry() -> SensorRegistry:
    return SensorRegistry(
        make_entries(
            zone_capacity=60,
            zone_area_sq_meters=120.0,
            zone_schedule_start_hour=8,
            zone_schedule_end_hour=18,
        )
    )


@pytest.fixture
def busy_controls() -> ScheduleControlsProvider:
    """
    Bypasses the schedule so a tick always looks like a full
    lecture, keeping assertions about readings predictable.
    """

    def provider(when, entry):
        return SimulationControls(
            occupancy_target=45,
            hvac_enabled=True,
            hvac_setpoint_c=22.0,
            ventilation_ach=3.0,
            outdoor_temp_c=30.0,
            outdoor_humidity_pct=55.0,
            solar_irradiance_w_m2=300.0,
        )

    return provider


def build(registry, **kwargs) -> TelemetrySimulator:
    kwargs.setdefault("clock", lambda: TICK_AT)
    kwargs.setdefault(
        "app_settings", FakeSettings(mqtt_enabled=False)
    )

    return TelemetrySimulator(registry=registry, **kwargs)


# --- Registry validation ----------------------------------------


def test_missing_registry_is_rejected():
    with pytest.raises(SimulatorError):
        TelemetrySimulator(registry=None)


def test_registry_missing_a_metric_is_rejected():
    partial = SensorRegistry(
        [
            make_entry("TEMP-LH01", "temperature", "°C"),
            make_entry("HUM-LH01", "humidity", "%"),
        ]
    )

    with pytest.raises(SimulatorError) as excinfo:
        TelemetrySimulator(registry=partial)

    assert "missing metrics" in str(excinfo.value)


def test_registry_with_bad_unit_is_rejected():
    broken = SensorRegistry(
        [
            make_entry("CO2-LH01", "co2", "ppm"),
            make_entry("ENERGY-LH01", "energy", "kW"),
            make_entry("HUM-LH01", "humidity", "F"),
            make_entry("OCC-LH01", "occupancy", "people"),
            make_entry("TEMP-LH01", "temperature", "°C"),
        ]
    )

    with pytest.raises(SimulatorError) as excinfo:
        TelemetrySimulator(registry=broken)

    assert "not valid for" in str(excinfo.value)


def test_registry_missing_location_is_rejected():
    broken = SensorRegistry(
        [
            SensorEntry(
                sensor_id=entry.sensor_id,
                sensor_code=entry.sensor_code,
                sensor_type=entry.sensor_type,
                unit=entry.unit,
                status=entry.status,
                campus_id=entry.campus_id,
                campus_code=entry.campus_code,
                building_id=entry.building_id,
                building_code=entry.building_code,
                floor_id=entry.floor_id,
                floor_code=entry.floor_code,
                zone_id=entry.zone_id,
                zone_code="",
            )
            if entry.metric == "temperature"
            else entry
            for entry in make_entries(
                zone_capacity=60, zone_area_sq_meters=120.0
            )
        ]
    )

    with pytest.raises(SimulatorError) as excinfo:
        TelemetrySimulator(registry=broken)

    assert "missing zone_code" in str(excinfo.value)


# --- Tick generation --------------------------------------------


def test_tick_produces_one_reading_per_sensor(
    registry, busy_controls
):
    simulator = build(
        registry, controls_provider=busy_controls
    )

    readings = simulator.build_tick()

    assert len(readings) == len(registry) == 5
    assert {
        reading.message.metric for reading in readings
    } == {
        "co2",
        "energy",
        "humidity",
        "occupancy",
        "temperature",
    }


def test_topics_are_valid_and_use_registry_uuids(
    registry, busy_controls
):
    simulator = build(
        registry, controls_provider=busy_controls
    )

    topics = {
        reading.topic for reading in simulator.build_tick()
    }

    assert len(topics) == 5

    for reading in simulator.build_tick():
        parsed = parse_topic(reading.topic)

        assert parsed.prefix == "smart-campus"
        assert parsed.campus_code == "CIT-MAIN"
        assert parsed.building_code == "ACADEMIC-BLK-A"
        assert parsed.floor_code == "A-F1"
        assert parsed.zone_code == "LH01"

    for entry in registry:
        assert any(
            entry.topic_ok(reading.topic)
            if hasattr(entry, "topic_ok")
            else str(entry.sensor_id) in reading.topic
            for reading in simulator.build_tick()
        )


def test_payloads_are_compact_json_that_revalidate(
    registry, busy_controls
):
    simulator = build(
        registry, controls_provider=busy_controls
    )

    for reading in simulator.build_tick():
        # Compact: no spaces after separators.
        assert ", " not in reading.payload
        assert '": ' not in reading.payload

        body = json.loads(reading.payload)

        # A consumer can rebuild the model from the payload.
        rebuilt = TelemetryMessage(**body)

        assert rebuilt == reading.message


def test_payload_carries_simulator_source_and_good_quality(
    registry, busy_controls
):
    simulator = build(
        registry, controls_provider=busy_controls
    )

    for reading in simulator.build_tick():
        assert reading.message.source == "simulator"
        assert reading.message.quality == "good"
        assert reading.message.metadata["simulated"] is True


def test_timestamps_are_timezone_aware_iso8601(
    registry, busy_controls
):
    simulator = build(
        registry, controls_provider=busy_controls
    )

    for reading in simulator.build_tick():
        body = json.loads(reading.payload)
        stamp = body["timestamp"]

        assert stamp.endswith("Z") or "+" in stamp

        parsed = datetime.fromisoformat(stamp)

        assert parsed.tzinfo is not None
        assert parsed == TICK_AT


def test_readings_carry_registry_location_ids(
    registry, busy_controls
):
    simulator = build(
        registry, controls_provider=busy_controls
    )

    for reading in simulator.build_tick():
        entry = next(
            item
            for item in registry
            if item.metric == reading.message.metric
        )

        assert reading.message.sensor_id == entry.sensor_id
        assert reading.message.zone_id == entry.zone_id
        assert reading.message.campus_id == entry.campus_id
        assert reading.message.unit == entry.unit


def test_values_are_physically_plausible(
    registry, busy_controls
):
    simulator = build(
        registry, controls_provider=busy_controls
    )

    readings = {
        reading.message.metric: reading.message.value
        for reading in simulator.build_tick()
    }

    assert 0 <= readings["occupancy"] <= 60
    assert readings["co2"] > 400
    assert readings["energy"] >= 0
    assert 0 <= readings["humidity"] <= 100


def test_energy_reading_uses_seeded_zone_capacity(
    registry, busy_controls
):
    """
    The capacity in the registry drives the model, so
    occupancy can never exceed it.
    """

    simulator = build(
        registry, controls_provider=busy_controls
    )

    readings = {
        reading.message.metric: reading.message.value
        for reading in simulator.build_tick()
    }

    assert readings["occupancy"] == 45.0


def test_consecutive_ticks_advance_the_model(
    registry, busy_controls
):
    simulator = build(
        registry, controls_provider=busy_controls
    )

    first = {
        reading.message.metric: reading.message.value
        for reading in simulator.build_tick()
    }

    second = {
        reading.message.metric: reading.message.value
        for reading in simulator.build_tick()
    }

    assert first["co2"] != second["co2"]
    assert first["occupancy"] == second["occupancy"]


def test_ticks_are_reproducible_with_a_fixed_clock(
    registry, busy_controls
):
    first = build(registry, controls_provider=busy_controls)
    second = build(registry, controls_provider=busy_controls)

    payloads_a = [
        r.payload for r in first.build_tick()
    ]
    payloads_b = [
        r.payload for r in second.build_tick()
    ]

    assert payloads_a == payloads_b


def test_naive_clock_is_rejected(registry):
    simulator = build(
        registry,
        clock=lambda: datetime(2026, 3, 3, 11, 0),
    )

    with pytest.raises(SimulatorError):
        simulator.build_tick()


# --- Disabled behaviour -----------------------------------------


def test_disabled_simulator_does_not_connect_or_publish(
    registry, busy_controls
):
    client = FakeMqttClient()

    simulator = build(
        registry,
        client=client,
        controls_provider=busy_controls,
        app_settings=FakeSettings(mqtt_enabled=False),
    )

    asyncio.run(simulator.run(max_ticks=3))

    assert client.entered == 0
    assert client.published == []


def test_disabled_simulator_start_returns_no_task(
    registry, busy_controls
):
    client = FakeMqttClient()

    simulator = build(
        registry,
        client=client,
        controls_provider=busy_controls,
        app_settings=FakeSettings(mqtt_enabled=False),
    )

    assert simulator.start() is None
    assert client.entered == 0


def test_ticking_itself_never_publishes(
    registry, busy_controls
):
    """
    build_tick is pure with respect to MQTT; only
    publish_tick sends.
    """

    client = FakeMqttClient()

    simulator = build(
        registry,
        client=client,
        controls_provider=busy_controls,
    )

    simulator.build_tick()

    assert client.published == []


# --- Lifecycle ---------------------------------------------------


def test_run_publishes_five_messages_per_tick(
    registry, busy_controls
):
    client = FakeMqttClient()

    simulator = build(
        registry,
        client=client,
        controls_provider=busy_controls,
        app_settings=FakeSettings(
            mqtt_enabled=True, telemetry_tick_seconds=0.01
        ),
    )

    asyncio.run(simulator.run(max_ticks=3))

    assert client.entered == 1
    assert client.exited == 1
    assert len(client.published) == 15


def test_published_payloads_validate_against_the_model(
    registry, busy_controls
):
    client = FakeMqttClient()

    simulator = build(
        registry,
        client=client,
        controls_provider=busy_controls,
        app_settings=FakeSettings(
            mqtt_enabled=True, telemetry_tick_seconds=0.01
        ),
    )

    asyncio.run(simulator.run(max_ticks=1))

    topics = set()

    for topic, payload, qos in client.published:
        assert qos == 0
        parse_topic(topic)
        topics.add(topic)

        body = json.loads(payload.decode("utf-8"))
        message = TelemetryMessage(**body)

        assert message.source == "simulator"

    assert len(topics) == 5


def test_stop_cancels_the_loop_and_disconnects(
    registry, busy_controls
):
    client = FakeMqttClient()

    simulator = build(
        registry,
        client=client,
        controls_provider=busy_controls,
        app_settings=FakeSettings(
            mqtt_enabled=True,
            # Long interval so the loop is asleep when stopped.
            telemetry_tick_seconds=60,
        ),
    )

    async def scenario():
        task = simulator.start()

        # Let the first tick publish, then stop.
        await asyncio.sleep(0.05)

        await simulator.stop()

        return task

    task = asyncio.run(scenario())

    assert task.done()
    assert client.entered == 1
    assert client.exited == 1
    assert len(client.published) == 5


def test_stop_without_start_is_a_no_op(registry):
    simulator = build(registry)

    asyncio.run(simulator.stop())


def test_start_is_idempotent(registry, busy_controls):
    client = FakeMqttClient()

    simulator = build(
        registry,
        client=client,
        controls_provider=busy_controls,
        app_settings=FakeSettings(
            mqtt_enabled=True, telemetry_tick_seconds=60
        ),
    )

    async def scenario():
        first = simulator.start()
        second = simulator.start()

        assert first is second

        # Let the loop reach its first await before cancelling.
        await asyncio.sleep(0.05)

        await simulator.stop()

    asyncio.run(scenario())

    assert client.entered == 1


def test_async_context_manager_starts_and_stops(
    registry, busy_controls
):
    client = FakeMqttClient()

    simulator = build(
        registry,
        client=client,
        controls_provider=busy_controls,
        app_settings=FakeSettings(
            mqtt_enabled=True, telemetry_tick_seconds=60
        ),
    )

    async def scenario():
        async with simulator:
            await asyncio.sleep(0.05)

    asyncio.run(scenario())

    assert client.entered == 1
    assert client.exited == 1


def test_publish_failure_propagates_and_disconnects(
    registry, busy_controls
):
    client = FakeMqttClient()
    client.publish_error = RuntimeError("broker gone")

    simulator = build(
        registry,
        client=client,
        controls_provider=busy_controls,
        app_settings=FakeSettings(
            mqtt_enabled=True, telemetry_tick_seconds=0.01
        ),
    )

    with pytest.raises(RuntimeError, match="broker gone"):
        asyncio.run(simulator.run(max_ticks=1))

    assert client.exited == 1


# --- Schedule controls ------------------------------------------


def test_schedule_provider_is_empty_outside_hours(
    registry,
):
    provider = ScheduleControlsProvider(
        capacity=60, start_hour=8, end_hour=18
    )

    entry = next(iter(registry))

    # 03:00 local on a Wednesday.
    controls = provider(
        datetime(2026, 3, 4, 3, 0, tzinfo=timezone.utc),
        entry,
    )

    assert 0 <= controls.occupancy_target <= 60


def test_schedule_provider_capacity_is_bounded(registry):
    provider = ScheduleControlsProvider(capacity=60)

    entry = next(iter(registry))

    for hour in range(0, 24):
        controls = provider(
            datetime(2026, 3, 3, hour, 30, tzinfo=timezone.utc),
            entry,
        )

        assert 0 <= controls.occupancy_target <= 60


def test_schedule_provider_is_deterministic(registry):
    provider = ScheduleControlsProvider(capacity=60)

    entry = next(iter(registry))

    when = datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc)

    assert provider(when, entry) == provider(when, entry)


def test_zone_values_from_registry_reach_the_model(registry):
    simulator = build(registry)

    parameters = simulator._resolved_parameters(
        next(iter(registry))
    )

    assert parameters.zone_capacity == 60
    assert parameters.zone_area_sq_m == 120.0


def test_unknown_sensor_lookup_still_raises(registry):
    from uuid import UUID

    with pytest.raises(UnknownSensorError):
        registry.get_by_id(
            UUID("00000000-0000-4000-8000-000000000000")
        )


def test_encode_payload_is_stable():
    message = TelemetryMessage(
        sensor_id=SEED_IDS["OCC-LH01"],
        metric="occupancy",
        value=12.0,
        unit="people",
        timestamp=TICK_AT,
        source="simulator",
        quality="good",
    )

    first = encode_payload(message)
    second = encode_payload(message)

    assert first == second
    assert '"source":"simulator"' in first


def test_parameters_override_is_honoured(registry):
    parameters = SimulationParameters(
        zone_capacity=25, zone_area_sq_m=50.0
    )

    simulator = build(registry, parameters=parameters)

    resolved = simulator._resolved_parameters(
        next(iter(registry))
    )

    # Registry values win over the injected defaults.
    assert resolved.zone_capacity == 60


def test_initial_state_matches_zone_defaults(registry):
    simulator = build(registry)

    assert simulator.state.occupancy == 0
    assert simulator.state.co2_ppm == 420.0


def test_building_a_reading_uses_registry_topic_helpers(
    registry, busy_controls
):
    """
    The simulator must not invent topics: they come from
    build_topic in Stage 3.
    """

    simulator = build(
        registry, controls_provider=busy_controls
    )

    for reading, entry in zip(
        simulator.build_tick(), list(registry)
    ):
        assert reading.topic.endswith(str(entry.sensor_id))
        assert isinstance(reading.message, TelemetryMessage)
        assert isinstance(
            simulator.state, SimulationState
        )