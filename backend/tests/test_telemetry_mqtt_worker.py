"""
MQTT ingestion worker tests.

Fully offline: fake MQTT client and messages, fake registry
loader, fake writer. No broker connection, no Supabase, no
network. Async behaviour uses `asyncio.run`, so no additional
pytest plugin is needed.
"""

import asyncio
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.telemetry.models import TelemetryMessage
from app.telemetry.mqtt_worker import (
    REASON_LOCATION_MISMATCH,
    REASON_METRIC_MISMATCH,
    REASON_PAYLOAD_ENCODING,
    REASON_PAYLOAD_JSON,
    REASON_PAYLOAD_NOT_OBJECT,
    REASON_SCHEMA_INVALID,
    REASON_SENSOR_MISMATCH,
    REASON_TOPIC_MALFORMED,
    REASON_UNIT_MISMATCH,
    REASON_UNKNOWN_SENSOR,
    WRITER_ERROR,
    MqttTelemetryWorker,
)
from app.telemetry.registry import SensorEntry, SensorRegistry
from app.telemetry.topics import build_topic


from conftest import (
    CAMPUS_ID,
    BUILDING_ID,
    FLOOR_ID,
    SEED_IDS,
    ZONE_ID,
    EQUIPMENT_ID,
    make_entry,
)


TICK_AT = datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc)
UNKNOWN_UUID = "00000000-0000-4000-8000-00000000dead"


@dataclass
class FakeSettings:
    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "smart-campus"
    telemetry_tick_seconds: int = 5
    telemetry_flush_seconds: int = 10


class FakeMessage:
    """Mirrors aiomqtt.Message's shape as the worker uses it."""

    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload
        self.qos = 0
        self.retain = False
        self.mid = 1
        self.properties = None


class FakeStream:
    """
    Async iterator over canned messages.

    `block` keeps the worker parked (as a live connection
    would) so stop and cancellation can be tested.
    """

    def __init__(
        self,
        messages,
        block: bool = False,
        end_error: Exception = None,
    ) -> None:
        self._messages = list(messages)
        self._block = block
        self._end_error = end_error

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)

        if self._end_error is not None:
            raise self._end_error

        if self._block:
            await asyncio.Event().wait()

        raise StopAsyncIteration


class FakeClient:
    """
    Stands in for aiomqtt.Client. Records subscriptions and
    connection lifecycle.
    """

    def __init__(
        self,
        messages=None,
        connect_error: Exception = None,
        block: bool = False,
        end_error: Exception = None,
    ) -> None:
        self._messages = messages or []
        self._connect_error = connect_error
        self._block = block
        self._end_error = end_error

        self.entered = 0
        self.exited = 0
        self.subscriptions = []

    async def __aenter__(self):
        if self._connect_error is not None:
            raise self._connect_error

        self.entered += 1
        return self

    async def __aexit__(self, *_exc_info):
        self.exited += 1

    async def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))

    @property
    def messages(self):
        return FakeStream(
            self._messages,
            block=self._block,
            end_error=self._end_error,
        )


class FakeWriter:
    """
    Records enqueued messages and can be told to fail.
    """

    def __init__(self, error: Exception = None) -> None:
        self.messages = []
        self.error = error
        self.closed = False
        self.close_calls = 0

    async def enqueue_async(self, message):
        if self.error is not None:
            raise self.error

        self.messages.append(message)

    async def close_async(self, drain: bool = True):
        self.close_calls += 1
        self.closed = True


def make_registry(entries=None) -> SensorRegistry:
    entries = entries or [
        make_entry("CO2-LH01", "co2", "ppm"),
        make_entry("ENERGY-LH01", "energy", "kW"),
        make_entry("HUM-LH01", "humidity", "%"),
        make_entry("OCC-LH01", "occupancy", "people"),
        make_entry("TEMP-LH01", "temperature", "°C"),
    ]

    return SensorRegistry(
        [
            SensorEntry(
                **{
                    **entry.__dict__,
                    "zone_capacity": 60,
                    "zone_area_sq_meters": 120.0,
                    "zone_schedule_start_hour": 8,
                    "zone_schedule_end_hour": 18,
                    "equipment_rated_power_kw": 12.5,
                }
            )
            for entry in entries
        ]
    )


def payload_for(entry, **overrides) -> bytes:
    """
    A payload the Stage 3 model accepts, as the Stage 4
    simulator would emit it.
    """

    values = {
        "sensor_id": entry.sensor_id,
        "metric": entry.metric,
        "value": 24.5,
        "unit": entry.unit,
        "timestamp": TICK_AT,
        "source": "simulator",
        "quality": "good",
        "campus_id": entry.campus_id,
        "building_id": entry.building_id,
        "floor_id": entry.floor_id,
        "zone_id": entry.zone_id,
        "equipment_id": entry.equipment_id,
        "metadata": {"simulated": True},
    }
    values.update(overrides)

    message = TelemetryMessage(**values)

    return json.dumps(
        message.model_dump(mode="json")
    ).encode("utf-8")


def build_worker(
    registry=None,
    writer=None,
    client_factory=None,
    enabled: bool = True,
    **kwargs,
) -> MqttTelemetryWorker:
    kwargs.setdefault("reconnect_backoff_seconds", 0.01)
    kwargs.setdefault("max_backoff_seconds", 0.02)

    return MqttTelemetryWorker(
        writer=writer if writer is not None else FakeWriter(),
        registry=(
            registry if registry is not None else make_registry()
        ),
        client_factory=client_factory,
        app_settings=FakeSettings(mqtt_enabled=enabled),
        **kwargs,
    )


@pytest.fixture
def temp_entry():
    return make_entry("TEMP-LH01", "temperature", "°C")


# --- Disabled mode ----------------------------------------------


def test_disabled_worker_never_connects(temp_entry):
    client = FakeClient()
    writer = FakeWriter()

    worker = build_worker(
        writer=writer,
        client_factory=lambda: client,
        enabled=False,
    )

    assert worker.start() is None

    asyncio.run(worker.run())

    assert client.entered == 0
    assert writer.messages == []


def test_disabled_worker_does_not_load_registry():
    calls = []

    worker = MqttTelemetryWorker(
        writer=FakeWriter(),
        registry_loader=lambda: calls.append(1),
        app_settings=FakeSettings(mqtt_enabled=False),
    )

    asyncio.run(worker.run())

    assert calls == []


# --- Accepting valid messages -----------------------------------


def test_valid_message_is_accepted_and_enqueued(temp_entry):
    writer = FakeWriter()
    worker = build_worker(writer=writer)

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry), payload_for(temp_entry)
        )
    )

    assert outcome == "accepted"
    assert len(writer.messages) == 1

    accepted = writer.messages[0]

    assert accepted.sensor_id == temp_entry.sensor_id
    assert accepted.metric == "temperature"
    assert accepted.unit == "°C"
    assert worker.stats.messages_received == 1
    assert worker.stats.messages_accepted == 1
    assert worker.stats.messages_rejected == 0


def test_simulator_source_and_metadata_are_preserved(
    temp_entry,
):
    writer = FakeWriter()
    worker = build_worker(writer=writer)

    asyncio.run(
        worker.handle_message(
            build_topic(temp_entry), payload_for(temp_entry)
        )
    )

    accepted = writer.messages[0]

    # Simulated data is never relabelled as sensor data.
    assert accepted.source == "simulator"
    assert accepted.metadata["simulated"] is True
    assert accepted.source != "sensor"


def test_all_five_sensors_are_accepted():
    registry = make_registry()
    writer = FakeWriter()
    worker = build_worker(registry=registry, writer=writer)

    for entry in registry:
        outcome = asyncio.run(
            worker.handle_message(
                build_topic(entry), payload_for(entry)
            )
        )

        assert outcome == "accepted"

    assert len(writer.messages) == 5
    assert worker.stats.messages_accepted == 5


def test_missing_location_ids_are_filled_from_the_registry():
    registry = make_registry()
    entry = next(
        item for item in registry
        if item.sensor_code == "ENERGY-LH01"
    )

    writer = FakeWriter()
    worker = build_worker(registry=registry, writer=writer)

    payload = payload_for(
        entry,
        campus_id=None,
        building_id=None,
        floor_id=None,
        zone_id=None,
        equipment_id=None,
    )

    outcome = asyncio.run(
        worker.handle_message(build_topic(entry), payload)
    )

    assert outcome == "accepted"

    accepted = writer.messages[0]

    assert accepted.zone_id == entry.zone_id
    assert accepted.campus_id == entry.campus_id
    assert accepted.equipment_id == entry.equipment_id


# --- Rejections -------------------------------------------------


def test_malformed_topic_is_rejected(temp_entry):
    worker = build_worker()

    outcome = asyncio.run(
        worker.handle_message(
            "smart-campus/campus/CIT-MAIN/sensor/nope",
            payload_for(temp_entry),
        )
    )

    assert outcome == REASON_TOPIC_MALFORMED
    assert (
        worker.stats.rejected_by_reason[REASON_TOPIC_MALFORMED] == 1
    )


def test_topic_with_wrong_prefix_is_rejected(temp_entry):
    worker = build_worker()

    topic = build_topic(temp_entry).replace(
        "smart-campus", "other-campus", 1
    )

    outcome = asyncio.run(
        worker.handle_message(topic, payload_for(temp_entry))
    )

    assert outcome == REASON_TOPIC_MALFORMED


def test_topic_with_malformed_uuid_is_rejected(temp_entry):
    worker = build_worker()

    topic = build_topic(temp_entry).rsplit("/", 1)[0] + "/1234"

    outcome = asyncio.run(
        worker.handle_message(topic, payload_for(temp_entry))
    )

    assert outcome == REASON_TOPIC_MALFORMED


def test_invalid_utf8_payload_is_rejected(temp_entry):
    worker = build_worker()

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry), b"\xff\xfe not utf-8"
        )
    )

    assert outcome == REASON_PAYLOAD_ENCODING


def test_malformed_json_is_rejected(temp_entry):
    worker = build_worker()

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry), b"{not json"
        )
    )

    assert outcome == REASON_PAYLOAD_JSON


def test_json_array_payload_is_rejected(temp_entry):
    worker = build_worker()

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry), b"[1, 2, 3]"
        )
    )

    assert outcome == REASON_PAYLOAD_NOT_OBJECT


def test_schema_violation_is_rejected(temp_entry):
    worker = build_worker()

    body = json.loads(payload_for(temp_entry))
    body["metric"] = "radiation"

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry),
            json.dumps(body).encode(),
        )
    )

    assert outcome == REASON_SCHEMA_INVALID


def test_non_finite_value_is_rejected(temp_entry):
    worker = build_worker()

    body = json.loads(payload_for(temp_entry))
    body["value"] = 1e999  # JSON cannot hold Infinity verbatim

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry),
            json.dumps(
                {**body, "value": float("inf")},
                allow_nan=True,
            ).encode(),
        )
    )

    assert outcome == REASON_SCHEMA_INVALID


def test_naive_timestamp_is_rejected(temp_entry):
    worker = build_worker()

    body = json.loads(payload_for(temp_entry))
    body["timestamp"] = "2026-03-03T10:00:00"

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry),
            json.dumps(body).encode(),
        )
    )

    assert outcome == REASON_SCHEMA_INVALID


def test_sensor_id_mismatch_between_topic_and_payload(temp_entry):
    worker = build_worker()

    other = make_entry("OCC-LH01", "occupancy", "people")

    # Temperature topic carrying the occupancy sensor's payload.
    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry), payload_for(other)
        )
    )

    assert outcome == REASON_SENSOR_MISMATCH


def test_unknown_sensor_is_rejected():
    registry = make_registry()

    topic = (
        "smart-campus/campus/CIT-MAIN"
        "/building/ACADEMIC-BLK-A"
        "/floor/A-F1"
        "/zone/LH01"
        f"/sensor/{UNKNOWN_UUID}"
    )

    body = json.loads(payload_for(registry.entries[0]))
    body["sensor_id"] = UNKNOWN_UUID

    worker = build_worker(registry=registry)

    outcome = asyncio.run(
        worker.handle_message(topic, json.dumps(body).encode())
    )

    assert outcome == REASON_UNKNOWN_SENSOR


def test_metric_mismatch_is_rejected(temp_entry):
    """
    A payload whose metric is valid but does not match the
    sensor the topic names.
    """

    worker = build_worker()

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry),
            payload_for(temp_entry, metric="co2", unit="ppm"),
        )
    )

    assert outcome == REASON_METRIC_MISMATCH


def test_unit_mismatch_against_registry_is_rejected():
    """
    The registry disagrees with the payload's unit even though
    the unit is valid for the metric on its own.
    """

    # The registry claims this sensor reports ppm; the payload
    # says °C, which is valid for temperature on its own.
    inconsistent = SensorEntry(
        **make_entry("TEMP-LH01", "temperature", "ppm").__dict__
    )

    registry = make_registry(
        [inconsistent]
        + [
            make_entry("CO2-LH01", "co2", "ppm"),
            make_entry("ENERGY-LH01", "energy", "kW"),
            make_entry("HUM-LH01", "humidity", "%"),
            make_entry("OCC-LH01", "occupancy", "people"),
        ]
    )

    good_entry = make_entry(
        "TEMP-LH01", "temperature", "°C"
    )

    writer = FakeWriter()
    worker = build_worker(registry=registry, writer=writer)

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(inconsistent),
            payload_for(good_entry),
        )
    )

    assert outcome == REASON_UNIT_MISMATCH
    assert writer.messages == []


def test_location_mismatch_is_rejected(temp_entry):
    worker = build_worker()

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry),
            payload_for(
                temp_entry,
                zone_id="99999999-0000-4000-8000-000000000000",
            ),
        )
    )

    assert outcome == REASON_LOCATION_MISMATCH


def test_one_bad_message_does_not_stop_the_worker(temp_entry):
    writer = FakeWriter()
    worker = build_worker(writer=writer)

    good = build_topic(temp_entry)

    async def scenario():
        await worker.handle_message("garbage", b"{}")
        await worker.handle_message(good, b"{bad json")
        await worker.handle_message(
            good, payload_for(temp_entry)
        )

    asyncio.run(scenario())

    assert len(writer.messages) == 1
    assert worker.stats.messages_received == 3
    assert worker.stats.messages_accepted == 1
    assert worker.stats.messages_rejected == 2


# --- Writer failures --------------------------------------------


def test_writer_error_does_not_kill_the_worker(temp_entry):
    writer = FakeWriter(
        error=RuntimeError("buffer full")
    )

    worker = build_worker(writer=writer)

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry), payload_for(temp_entry)
        )
    )

    assert outcome == WRITER_ERROR
    assert worker.stats.writer_errors == 1
    assert worker.stats.messages_accepted == 0

    # The worker keeps working: a later good message is still
    # processed once the writer recovers.
    writer.error = None

    second = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry), payload_for(temp_entry)
        )
    )

    assert second == "accepted"
    assert len(writer.messages) == 1


# --- Topic subscription -----------------------------------------


def test_topic_filter_is_narrow():
    worker = build_worker()

    topic_filter = asyncio.run(worker.build_topic_filter())

    assert topic_filter == (
        "smart-campus/campus/CIT-MAIN"
        "/building/ACADEMIC-BLK-A"
        "/floor/A-F1"
        "/zone/LH01"
        "/sensor/+"
    )

    # Never the whole tree.
    assert not topic_filter.endswith("#")
    assert "#" not in topic_filter


def test_topic_filter_can_be_overridden():
    worker = build_worker(
        topic_filter="smart-campus/+/+/+/+/+/+"
    )

    assert asyncio.run(worker.build_topic_filter()) == (
        "smart-campus/+/+/+/+/+/+"
    )


def test_run_subscribes_to_the_narrow_filter(temp_entry):
    client = FakeClient(
        messages=[
            FakeMessage(
                build_topic(temp_entry), payload_for(temp_entry)
            )
        ]
    )

    writer = FakeWriter()
    worker = build_worker(
        writer=writer, client_factory=lambda: client
    )

    asyncio.run(worker.run(max_messages=1))

    assert client.entered == 1
    assert client.exited == 1
    assert client.subscriptions == [
        (
            "smart-campus/campus/CIT-MAIN"
            "/building/ACADEMIC-BLK-A"
            "/floor/A-F1"
            "/zone/LH01"
            "/sensor/+",
            0,
        )
    ]
    assert len(writer.messages) == 1


def test_run_consumes_five_messages_per_tick(temp_entry):
    registry = make_registry()

    client = FakeClient(
        messages=[
            FakeMessage(
                build_topic(entry), payload_for(entry)
            )
            for entry in registry
        ]
    )

    writer = FakeWriter()
    worker = build_worker(
        registry=registry,
        writer=writer,
        client_factory=lambda: client,
    )

    asyncio.run(worker.run(max_messages=5))

    assert len(writer.messages) == 5
    assert worker.stats.messages_accepted == 5
    assert worker.stats.connections_established == 1


# --- Registry loading -------------------------------------------


def test_registry_is_loaded_off_the_event_loop():
    thread_ids = []

    def loader():
        thread_ids.append(threading.get_ident())
        return make_registry()

    writer = FakeWriter()
    worker = build_worker(registry=None, writer=writer)

    worker._registry = None
    worker._registry_loader = loader

    entry = make_entry("TEMP-LH01", "temperature", "°C")

    loop_thread = None

    async def scenario():
        nonlocal loop_thread
        loop_thread = threading.get_ident()

        await worker.handle_message(
            build_topic(entry), payload_for(entry)
        )

    asyncio.run(scenario())

    assert thread_ids
    assert thread_ids[0] != loop_thread
    assert len(writer.messages) == 1


def test_registry_is_loaded_once_not_per_message():
    calls = []

    def loader():
        calls.append(1)
        return make_registry()

    worker = build_worker(registry=None)
    worker._registry = None
    worker._registry_loader = loader

    entries = make_registry().entries

    async def scenario():
        for entry in entries:
            await worker.handle_message(
                build_topic(entry), payload_for(entry)
            )

    asyncio.run(scenario())

    assert len(calls) == 1
    assert worker.stats.messages_accepted == 5


def test_registry_load_failure_rejects_without_crashing(
    temp_entry,
):
    def loader():
        raise RuntimeError("supabase unavailable")

    worker = build_worker(registry=None)
    worker._registry = None
    worker._registry_loader = loader

    outcome = asyncio.run(
        worker.handle_message(
            build_topic(temp_entry), payload_for(temp_entry)
        )
    )

    assert outcome == REASON_UNKNOWN_SENSOR
    assert worker.stats.messages_rejected == 1


def test_unloaded_registry_property_raises():
    worker = MqttTelemetryWorker(
        writer=FakeWriter(),
        registry=None,
        registry_loader=lambda: make_registry(),
        app_settings=FakeSettings(mqtt_enabled=False),
    )

    with pytest.raises(RuntimeError):
        worker.registry


# --- Reconnect and backoff --------------------------------------


def test_connection_failure_is_counted_and_retried():
    from aiomqtt import MqttError

    failing = FakeClient(
        connect_error=MqttError("connection refused")
    )
    working = FakeClient(
        messages=[
            FakeMessage(
                "smart-campus/campus/CIT-MAIN"
                "/building/ACADEMIC-BLK-A"
                "/floor/A-F1"
                "/zone/LH01"
                "/sensor/" + SEED_IDS["TEMP-LH01"],
                payload_for(
                    make_entry("TEMP-LH01", "temperature", "°C")
                ),
            )
        ]
    )

    clients = [failing, working]

    writer = FakeWriter()
    worker = build_worker(
        writer=writer,
        client_factory=lambda: clients.pop(0),
    )

    asyncio.run(worker.run(max_messages=1))

    assert worker.stats.connection_failures == 1
    assert worker.stats.connections_established == 1
    assert len(writer.messages) == 1


def test_backoff_is_bounded_not_a_tight_loop():
    from aiomqtt import MqttError

    delays = []

    worker = build_worker(
        client_factory=lambda: FakeClient(
            connect_error=MqttError("refused")
        ),
        max_reconnect_attempts=4,
        reconnect_backoff_seconds=1.0,
        max_backoff_seconds=2.0,
    )

    # Record what the worker would sleep for, without actually
    # waiting.
    async def record(seconds):
        delays.append(seconds)
        return False

    worker._sleep_or_stop = record

    asyncio.run(worker.run())

    # Doubling each attempt, capped at the maximum.
    assert delays == [1.0, 2.0, 2.0]
    assert max(delays) <= 2.0
    assert worker.stats.connection_failures == 4


def test_reconnect_attempts_are_bounded():
    from aiomqtt import MqttError

    clients = []

    def factory():
        client = FakeClient(
            connect_error=MqttError("refused")
        )
        clients.append(client)
        return client

    worker = build_worker(
        client_factory=factory, max_reconnect_attempts=3
    )

    asyncio.run(worker.run())

    assert len(clients) == 3
    assert worker.stats.connection_failures == 3
    assert worker.is_running is False


def test_reconnect_after_clean_close(temp_entry):
    first = FakeClient(messages=[])
    second = FakeClient(
        messages=[
            FakeMessage(
                build_topic(temp_entry), payload_for(temp_entry)
            )
        ]
    )

    clients = [first, second]

    writer = FakeWriter()
    worker = build_worker(
        writer=writer,
        client_factory=lambda: clients.pop(0),
    )

    asyncio.run(worker.run(max_messages=1))

    assert first.entered == 1
    assert first.exited == 1
    assert second.entered == 1
    assert len(writer.messages) == 1
    assert worker.stats.connection_failures == 0


# --- Stop and cancellation --------------------------------------


def test_stop_closes_the_writer_and_the_connection():
    client = FakeClient(block=True)
    writer = FakeWriter()

    worker = build_worker(
        writer=writer, client_factory=lambda: client
    )

    async def scenario():
        task = worker.start()

        await asyncio.sleep(0.05)

        await worker.stop()

        return task

    task = asyncio.run(scenario())

    assert task.done()
    assert client.entered == 1
    assert client.exited == 1
    assert writer.closed
    assert worker.is_running is False


def test_stop_without_start_is_safe():
    worker = build_worker()

    asyncio.run(worker.stop())


def test_stop_survives_a_failing_writer_close():
    writer = FakeWriter()

    async def boom(drain=True):
        raise RuntimeError("writer wedged")

    writer.close_async = boom

    worker = build_worker(writer=writer)

    # Must not propagate: shutdown has to complete.
    asyncio.run(worker.stop())


def test_cancellation_propagates_and_disconnects(temp_entry):
    client = FakeClient(block=True)

    worker = build_worker(client_factory=lambda: client)

    async def scenario():
        task = worker.start()

        await asyncio.sleep(0.05)

        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert client.exited == 1


def test_async_context_manager_starts_and_stops():
    client = FakeClient(block=True)
    writer = FakeWriter()

    worker = build_worker(
        writer=writer, client_factory=lambda: client
    )

    async def scenario():
        async with worker:
            await asyncio.sleep(0.05)

    asyncio.run(scenario())

    assert client.entered == 1
    assert client.exited == 1
    assert writer.closed


def test_start_is_idempotent():
    client = FakeClient(block=True)

    worker = build_worker(client_factory=lambda: client)

    async def scenario():
        first = worker.start()
        second = worker.start()

        assert first is second

        await asyncio.sleep(0.05)
        await worker.stop()

    asyncio.run(scenario())

    assert client.entered == 1


# --- Counters ----------------------------------------------------


def test_counters_track_received_accepted_and_rejected(
    temp_entry,
):
    worker = build_worker()

    async def scenario():
        await worker.handle_message(
            build_topic(temp_entry), payload_for(temp_entry)
        )
        await worker.handle_message("garbage", b"{}")
        await worker.handle_message(
            build_topic(temp_entry), b"{"
        )

    asyncio.run(scenario())

    assert worker.stats.messages_received == 3
    assert worker.stats.messages_accepted == 1
    assert worker.stats.messages_rejected == 2
    assert worker.stats.rejected_by_reason == {
        REASON_TOPIC_MALFORMED: 1,
        REASON_PAYLOAD_JSON: 1,
    }
    assert sum(
        worker.stats.rejected_by_reason.values()
    ) == worker.stats.messages_rejected