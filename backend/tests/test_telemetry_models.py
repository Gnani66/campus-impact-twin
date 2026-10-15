"""
Telemetry message contract tests.

Pure validation, no I/O.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.telemetry.models import (
    SEED_METRIC_UNITS,
    TelemetryMessage,
)


from conftest import SEED_IDS, ZONE_ID, EQUIPMENT_ID


UTC = timezone.utc
SENSOR_ID = SEED_IDS["TEMP-LH01"]


def valid_payload(**overrides) -> dict:
    payload = {
        "sensor_id": SENSOR_ID,
        "metric": "temperature",
        "value": 24.5,
        "unit": "°C",
        "timestamp": datetime(2026, 3, 2, 9, 15, tzinfo=UTC),
        "source": "simulator",
        "quality": "good",
        "zone_id": ZONE_ID,
    }

    payload.update(overrides)

    return payload


def test_valid_message_is_accepted():
    message = TelemetryMessage(**valid_payload())

    assert message.metric == "temperature"
    assert message.unit == "°C"
    assert message.value == 24.5
    assert message.sensor_id == SENSOR_ID or (
        str(message.sensor_id) == SENSOR_ID
    )
    assert message.quality == "good"


@pytest.mark.parametrize(
    "metric,unit", sorted(SEED_METRIC_UNITS.items())
)
def test_every_seeded_metric_accepts_its_own_unit(
    metric, unit
):
    """
    The five seeded sensors must all validate.
    """

    sensor_code = {
        "co2": "CO2-LH01",
        "energy": "ENERGY-LH01",
        "humidity": "HUM-LH01",
        "occupancy": "OCC-LH01",
        "temperature": "TEMP-LH01",
    }[metric]

    message = TelemetryMessage(
        **valid_payload(
            sensor_id=SEED_IDS[sensor_code],
            metric=metric,
            unit=unit[0],
            value=1.0,
        )
    )

    assert message.metric == metric


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_non_finite_values_are_rejected(value):
    with pytest.raises(ValidationError) as excinfo:
        TelemetryMessage(**valid_payload(value=value))

    assert "finite" in str(excinfo.value).lower()


def test_unknown_metric_is_rejected():
    with pytest.raises(ValidationError) as excinfo:
        TelemetryMessage(
            **valid_payload(metric="radiation")
        )

    assert "unknown metric" in str(excinfo.value)


def test_unit_from_another_metric_is_rejected():
    with pytest.raises(ValidationError) as excinfo:
        TelemetryMessage(
            **valid_payload(
                metric="temperature", unit="ppm"
            )
        )

    assert "not valid for metric" in str(excinfo.value)


def test_plausible_but_uninvented_unit_is_rejected():
    with pytest.raises(ValidationError):
        TelemetryMessage(
            **valid_payload(metric="co2", unit="percent")
        )


@pytest.mark.parametrize(
    "source", ["mqtt", "SIMULATOR", ""]
)
def test_invalid_source_is_rejected(source):
    with pytest.raises(ValidationError):
        TelemetryMessage(**valid_payload(source=source))


@pytest.mark.parametrize("quality", ["ok", "GOOD", "worst"])
def test_invalid_quality_is_rejected(quality):
    with pytest.raises(ValidationError):
        TelemetryMessage(**valid_payload(quality=quality))


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValidationError) as excinfo:
        TelemetryMessage(
            **valid_payload(
                timestamp=datetime(2026, 3, 2, 9, 15)
            )
        )

    assert "timezone-aware" in str(excinfo.value)


def test_non_utc_offset_timestamp_is_accepted():
    offset = timezone(timedelta(hours=5, minutes=30))

    message = TelemetryMessage(
        **valid_payload(
            timestamp=datetime(
                2026, 3, 2, 9, 15, tzinfo=offset
            )
        )
    )

    assert message.timestamp.utcoffset() == offset.utcoffset(None)


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        TelemetryMessage(
            **valid_payload(unexpected="payload")
        )


def test_invalid_sensor_id_is_rejected():
    with pytest.raises(ValidationError):
        TelemetryMessage(**valid_payload(sensor_id="not-a-uuid"))


def test_to_row_matches_telemetry_readings_columns():
    message = TelemetryMessage(
        **valid_payload(
            equipment_id=EQUIPMENT_ID,
            metadata={"source_detail": "sim"},
        )
    )

    row = message.to_row()

    assert set(row) == {
        "metric",
        "value",
        "unit",
        "timestamp",
        "source",
        "quality",
        "metadata",
        "sensor_id",
        "campus_id",
        "building_id",
        "floor_id",
        "zone_id",
        "equipment_id",
    }

    assert row["sensor_id"] == SENSOR_ID
    assert row["zone_id"] == ZONE_ID
    assert row["equipment_id"] == EQUIPMENT_ID
    assert row["metadata"] == {"source_detail": "sim"}

    # Absent identifiers stay None rather than a string.
    assert row["campus_id"] is None
    assert row["building_id"] is None
    assert row["floor_id"] is None


def test_non_finite_value_never_reaches_to_row():
    """
    The rejection happens at construction, so there is no
    partially valid message to write.
    """

    with pytest.raises(ValidationError):
        TelemetryMessage(
            **valid_payload(value=float("nan"))
        )

# --- JSON serialisation of the database row --------------------
#
# The PostgREST client serialises the insert body with
# json.dumps, so every value in to_row() must be JSON-safe.
# A datetime here broke the first live insert.


def test_row_is_json_serialisable():
    row = TelemetryMessage(**valid_payload()).to_row()

    # Compact separators, the same way the simulator encodes
    # a payload.
    encoded = json.dumps(row, separators=(",", ":"))

    assert '"metric":"temperature"' in encoded
    assert '"unit":"\\u00b0C"' in encoded or '"unit":"°C"' in encoded


def test_row_timestamp_is_an_iso8601_string():
    row = TelemetryMessage(**valid_payload()).to_row()

    expected = datetime(2026, 3, 2, 9, 15, tzinfo=UTC)

    assert isinstance(row["timestamp"], str)
    assert row["timestamp"] == expected.isoformat()


def test_row_timestamp_keeps_its_timezone():
    offset = timezone(timedelta(hours=5, minutes=30))

    when = datetime(2026, 3, 2, 9, 15, tzinfo=offset)

    row = TelemetryMessage(
        **valid_payload(timestamp=when)
    ).to_row()

    assert row["timestamp"].endswith("+05:30")

    # Same instant, same offset after parsing.
    parsed = datetime.fromisoformat(row["timestamp"])

    assert parsed == when
    assert parsed.utcoffset() == offset.utcoffset(None)


def test_row_timestamp_round_trips_utc():
    row = TelemetryMessage(
        **valid_payload(
            timestamp=datetime(
                2026, 3, 2, 9, 15, tzinfo=timezone.utc
            )
        )
    ).to_row()

    parsed = datetime.fromisoformat(row["timestamp"])

    assert parsed.tzinfo is not None
    assert parsed == datetime(2026, 3, 2, 9, 15, tzinfo=UTC)


def test_row_json_keeps_columns_source_quality_metadata():
    row = TelemetryMessage(
        **valid_payload(
            source="simulator",
            quality="suspect",
            metadata={"simulated": True, "run": "abc"},
            equipment_id=EQUIPMENT_ID,
        )
    ).to_row()

    decoded = json.loads(json.dumps(row))

    assert set(decoded) == {
        "metric",
        "value",
        "unit",
        "timestamp",
        "source",
        "quality",
        "metadata",
        "sensor_id",
        "campus_id",
        "building_id",
        "floor_id",
        "zone_id",
        "equipment_id",
    }
    assert decoded["source"] == "simulator"
    assert decoded["quality"] == "suspect"
    assert decoded["metadata"] == {
        "simulated": True, "run": "abc"
    }
    assert decoded["unit"] == "°C"
    assert decoded["value"] == 24.5
    assert decoded["equipment_id"] == EQUIPMENT_ID
    assert decoded["sensor_id"] == SENSOR_ID


def test_every_row_value_is_a_json_primitive():
    row = TelemetryMessage(
        **valid_payload(
            metadata={"nested": {"a": [1, 2, 3]}}
        )
    ).to_row()

    for column, value in row.items():
        assert isinstance(
            value, (str, int, float, dict, type(None))
        ), f"{column} is not JSON-safe: {type(value)}"


def test_writer_row_reaches_postgrest_serialiser():
    """
    Same call the real insert makes, without a network
    request: postgrest encodes the body with json.dumps.
    """

    from httpx._content import encode_json

    row = TelemetryMessage(
        **valid_payload(
            metadata={"simulated": True}
        )
    ).to_row()

    headers, stream = encode_json(row)

    body = b"".join(stream)

    assert b'"metric":"temperature"' in body
    assert "content-type" in {
        key.lower() for key in headers
    }
