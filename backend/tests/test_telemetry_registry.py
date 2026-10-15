"""
Sensor registry tests.

Driven by a fake Supabase client, so nothing here touches the
network, credentials or the real database.
"""

from uuid import UUID

import pytest

from app.telemetry.registry import (
    RegistryError,
    SensorRegistry,
    UnknownSensorError,
    get_registry,
    load_registry,
    reset_registry,
)
from app.telemetry.topics import build_topic, parse_topic


from conftest import (
    EQUIPMENT_ID,
    SEED_IDS,
    ZONE_ID,
    FakeSupabase,
    seed_tables,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_registry()
    yield
    reset_registry()


def test_loads_the_five_active_seeds(fake_supabase):
    registry = load_registry(client=fake_supabase)

    assert len(registry) == 5
    assert sorted(registry.sensor_codes) == [
        "CO2-LH01",
        "ENERGY-LH01",
        "HUM-LH01",
        "OCC-LH01",
        "TEMP-LH01",
    ]


def test_only_active_sensors_are_queried(fake_supabase):
    load_registry(client=fake_supabase)

    # eq(status="active") is applied, so an inactive row in
    # the fixture would be filtered out by the fake client.
    fake_supabase.tables["sensors"].append(
        {
            "id": "ffffffff-0000-4000-8000-0000000000ff",
            "zone_id": ZONE_ID,
            "equipment_id": None,
            "code": "OFF-LH01",
            "name": "Disabled Sensor",
            "sensor_type": "temperature",
            "unit": "°C",
            "status": "inactive",
            "sampling_interval_seconds": 5,
        }
    )

    registry = load_registry(client=fake_supabase)

    assert "OFF-LH01" not in registry.sensor_codes


def test_entry_retains_ids_codes_metric_and_unit(
    fake_supabase,
):
    registry = load_registry(client=fake_supabase)

    entry = registry.get_by_code("TEMP-LH01")

    assert entry.sensor_id == UUID(SEED_IDS["TEMP-LH01"])
    assert entry.sensor_code == "TEMP-LH01"
    assert entry.metric == "temperature"
    assert entry.unit == "°C"
    assert entry.campus_code == "CIT-MAIN"
    assert entry.building_code == "ACADEMIC-BLK-A"
    assert entry.floor_code == "A-F1"
    assert entry.zone_code == "LH01"
    assert entry.zone_id == UUID(ZONE_ID)


def test_equipment_relationship_is_preserved(
    fake_supabase,
):
    registry = load_registry(client=fake_supabase)

    energy = registry.get_by_code("ENERGY-LH01")
    temperature = registry.get_by_code("TEMP-LH01")

    assert energy.equipment_id == UUID(EQUIPMENT_ID)
    assert energy.equipment_code == "HVAC-LH01"
    assert temperature.equipment_id is None


def test_lookup_by_uuid(fake_supabase):
    registry = load_registry(client=fake_supabase)

    entry = registry.get_by_id(
        UUID(SEED_IDS["CO2-LH01"])
    )

    assert entry.sensor_code == "CO2-LH01"


def test_unknown_sensor_id_raises(fake_supabase):
    registry = load_registry(client=fake_supabase)

    with pytest.raises(UnknownSensorError):
        registry.get_by_id(
            UUID("00000000-0000-4000-8000-000000000000")
        )

    assert not registry.has(
        UUID("00000000-0000-4000-8000-000000000000")
    )


def test_unknown_sensor_code_raises(fake_supabase):
    registry = load_registry(client=fake_supabase)

    with pytest.raises(UnknownSensorError):
        registry.get_by_code("NOPE-LH01")


def test_duplicate_sensor_code_is_rejected():
    tables = seed_tables()
    tables["sensors"].append(dict(tables["sensors"][-1]))

    with pytest.raises(RegistryError) as excinfo:
        load_registry(client=FakeSupabase(tables))

    assert "duplicate sensor code" in str(excinfo.value)


def test_duplicate_sensor_id_is_rejected():
    tables = seed_tables()
    clone = dict(tables["sensors"][0])
    clone["code"] = "CO2-COPY"
    tables["sensors"].append(clone)

    with pytest.raises(RegistryError):
        load_registry(client=FakeSupabase(tables))


def test_duplicate_location_ids_are_rejected():
    """
    A repeated campus id must not be silently collapsed into
    one entry, or two campuses would become one.
    """

    tables = seed_tables()
    tables["campuses"].append(
        {"id": tables["campuses"][0]["id"], "code": "CIT-MAIN-2"}
    )

    with pytest.raises(RegistryError) as excinfo:
        load_registry(client=FakeSupabase(tables))

    assert "duplicate campus" in str(excinfo.value)


def test_invalid_sensor_uuid_is_rejected():
    tables = seed_tables()
    tables["sensors"][0]["id"] = "not-a-uuid"

    with pytest.raises(RegistryError) as excinfo:
        load_registry(client=FakeSupabase(tables))

    assert "not a valid uuid" in str(excinfo.value)


def test_sensor_with_unresolvable_zone_is_rejected():
    tables = seed_tables()
    tables["sensors"][0]["zone_id"] = "missing-zone"

    with pytest.raises(RegistryError) as excinfo:
        load_registry(client=FakeSupabase(tables))

    assert "unknown zone" in str(excinfo.value)


def test_unsupported_sensor_type_is_rejected():
    tables = seed_tables()
    tables["sensors"][0]["sensor_type"] = "radiation"

    with pytest.raises(RegistryError) as excinfo:
        load_registry(client=FakeSupabase(tables))

    assert "unsupported sensor_type" in str(excinfo.value)


def test_unit_not_valid_for_type_is_rejected():
    tables = seed_tables()
    tables["sensors"][0]["unit"] = "F"

    with pytest.raises(RegistryError) as excinfo:
        load_registry(client=FakeSupabase(tables))

    assert "not valid for" in str(excinfo.value)


def test_unknown_equipment_reference_is_rejected():
    tables = seed_tables()
    tables["sensors"][0]["equipment_id"] = "missing-equipment"

    with pytest.raises(RegistryError) as excinfo:
        load_registry(client=FakeSupabase(tables))

    assert "unknown equipment" in str(excinfo.value)


def test_empty_registry_is_rejected():
    with pytest.raises(RegistryError) as excinfo:
        SensorRegistry([])

    assert "registry is empty" in str(excinfo.value)


def test_registry_is_cached(fake_supabase):
    """
    A second read must not query the database again.

    The loader is wrapped rather than reloaded: reloading the
    module would rebind exception classes and break identity
    checks in other test modules.
    """

    import app.telemetry.registry as registry_module

    real_loader = registry_module.load_registry
    calls = {"count": 0}

    def counting_loader(client=None):
        calls["count"] += 1
        # Always the fake: get_registry() calls the loader
        # with no arguments.
        return real_loader(client=fake_supabase)

    registry_module.load_registry = counting_loader

    try:
        first = get_registry()
        second = get_registry()

        assert first is second
        assert calls["count"] == 1

        get_registry(force_refresh=True)

        assert calls["count"] == 2
    finally:
        registry_module.load_registry = real_loader


def test_entry_builds_a_parseable_topic(fake_supabase):
    registry = load_registry(client=fake_supabase)

    for entry in registry:
        parsed = parse_topic(build_topic(entry))

        assert str(parsed.sensor_id) == str(entry.sensor_id)
        assert parsed.zone_code == entry.zone_code


def test_topics_for_all_five_seeds_are_distinct(
    fake_supabase,
):
    registry = load_registry(client=fake_supabase)

    topics = {
        build_topic(entry) for entry in registry
    }

    assert len(topics) == 5