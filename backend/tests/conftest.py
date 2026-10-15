"""
Shared fixtures.

These tests run offline: no Supabase, no MQTT, no network.
Placeholder credentials are exported before any app module is
imported so `app.core.config` can construct Settings without a
real `.env`. Environment variables take precedence over the
dotenv file, so real values in `backend/.env` are never read
here.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List
from uuid import UUID


BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault(
    "SUPABASE_URL",
    "https://placeholder.supabase.co",
)
os.environ.setdefault(
    "SUPABASE_SERVICE_ROLE_KEY",
    "placeholder-service-role-key",
)
os.environ.setdefault("MQTT_ENABLED", "false")

import pytest  # noqa: E402

from app.telemetry.registry import (  # noqa: E402
    SensorEntry,
)


CAMPUS_ID = "0287767e-0000-4000-8000-000000000001"
BUILDING_ID = "94362040-0000-4000-8000-000000000002"
FLOOR_ID = "66467706-0000-4000-8000-000000000003"
ZONE_ID = "26f134ea-0000-4000-8000-000000000004"
EQUIPMENT_ID = "c19ffcca-0000-4000-8000-000000000005"

SEED_IDS = {
    "CO2-LH01": "a1000000-0000-4000-8000-00000000000c",
    "ENERGY-LH01": "e1000000-0000-4000-8000-00000000000e",
    "HUM-LH01": "b1000000-0000-4000-8000-00000000000d",
    "OCC-LH01": "f1000000-0000-4000-8000-00000000000f",
    "TEMP-LH01": "d1000000-0000-4000-8000-00000000000a",
}


def make_entry(
    sensor_code: str,
    sensor_type: str,
    unit: str,
    equipment_id: str = None,
) -> SensorEntry:
    """
    A registry entry shaped like the seeded LH01 sensors.
    """

    return SensorEntry(
        sensor_id=UUID(SEED_IDS[sensor_code]),
        sensor_code=sensor_code,
        sensor_type=sensor_type,
        unit=unit,
        status="active",
        campus_id=UUID(CAMPUS_ID),
        campus_code="CIT-MAIN",
        building_id=UUID(BUILDING_ID),
        building_code="ACADEMIC-BLK-A",
        floor_id=UUID(FLOOR_ID),
        floor_code="A-F1",
        zone_id=UUID(ZONE_ID),
        zone_code="LH01",
        equipment_id=(
            UUID(equipment_id)
            if equipment_id
            else None
        ),
        equipment_code=(
            "HVAC-LH01" if equipment_id else None
        ),
        sampling_interval_seconds=5,
    )


@pytest.fixture
def temperature_entry() -> SensorEntry:
    return make_entry(
        "TEMP-LH01", "temperature", "°C"
    )


@pytest.fixture
def energy_entry() -> SensorEntry:
    return make_entry(
        "ENERGY-LH01",
        "energy",
        "kW",
        equipment_id=EQUIPMENT_ID,
    )


class FakeResult:
    def __init__(self, data: List[dict]) -> None:
        self.data = data


class FakeTable:
    """
    Minimal stand-in for the PostgREST query chain used by
    `load_registry`: table().select().eq().execute().
    """

    def __init__(
        self,
        rows: List[dict],
        calls: List[str],
    ) -> None:
        self._rows = rows
        self._calls = calls
        self._filters: Dict[str, object] = {}

    def select(self, columns: str) -> "FakeTable":
        return self

    def eq(
        self,
        column: str,
        value: object,
    ) -> "FakeTable":
        self._filters[column] = value
        return self

    def execute(self) -> FakeResult:
        rows = self._rows

        for column, value in self._filters.items():
            rows = [
                row
                for row in rows
                if row.get(column) == value
            ]

        self._calls.append(self._table_name)

        return FakeResult([dict(row) for row in rows])

    _table_name = "?"


class FakeSupabase:
    """
    Serves canned rows per table and records which tables were
    read, so tests can assert the cache is doing its job.
    """

    def __init__(self, tables: Dict[str, List[dict]]) -> None:
        self.tables = tables
        self.calls: List[str] = []

    def table(self, name: str) -> FakeTable:
        if name not in self.tables:
            raise AssertionError(
                f"unexpected table queried: {name}"
            )

        handle = FakeTable(
            self.tables[name], self.calls
        )
        handle._table_name = name

        return handle

    @property
    def sensor_queries(self) -> int:
        return self.calls.count("sensors")


def seed_tables() -> Dict[str, List[dict]]:
    """
    The LH01 graph exactly as `002_seed_smart_campus.sql`
    creates it, with deterministic UUIDs.
    """

    return {
        "campuses": [
            {"id": CAMPUS_ID, "code": "CIT-MAIN"}
        ],
        "buildings": [
            {
                "id": BUILDING_ID,
                "campus_id": CAMPUS_ID,
                "code": "ACADEMIC-BLK-A",
            }
        ],
        "floors": [
            {
                "id": FLOOR_ID,
                "building_id": BUILDING_ID,
                "code": "A-F1",
            }
        ],
        "zones": [
            {
                "id": ZONE_ID,
                "floor_id": FLOOR_ID,
                "code": "LH01",
            }
        ],
        "equipment": [
            {
                "id": EQUIPMENT_ID,
                "code": "HVAC-LH01",
            }
        ],
        "sensors": [
            {
                "id": SEED_IDS["CO2-LH01"],
                "zone_id": ZONE_ID,
                "equipment_id": None,
                "code": "CO2-LH01",
                "name": "Lecture Hall CO2 Sensor",
                "sensor_type": "co2",
                "unit": "ppm",
                "status": "active",
                "sampling_interval_seconds": 5,
            },
            {
                "id": SEED_IDS["ENERGY-LH01"],
                "zone_id": ZONE_ID,
                "equipment_id": EQUIPMENT_ID,
                "code": "ENERGY-LH01",
                "name": "Lecture Hall Energy Meter",
                "sensor_type": "energy",
                "unit": "kW",
                "status": "active",
                "sampling_interval_seconds": 5,
            },
            {
                "id": SEED_IDS["HUM-LH01"],
                "zone_id": ZONE_ID,
                "equipment_id": None,
                "code": "HUM-LH01",
                "name": "Lecture Hall Humidity Sensor",
                "sensor_type": "humidity",
                "unit": "%",
                "status": "active",
                "sampling_interval_seconds": 5,
            },
            {
                "id": SEED_IDS["OCC-LH01"],
                "zone_id": ZONE_ID,
                "equipment_id": None,
                "code": "OCC-LH01",
                "name": "Lecture Hall Occupancy Sensor",
                "sensor_type": "occupancy",
                "unit": "people",
                "status": "active",
                "sampling_interval_seconds": 5,
            },
            {
                "id": SEED_IDS["TEMP-LH01"],
                "zone_id": ZONE_ID,
                "equipment_id": None,
                "code": "TEMP-LH01",
                "name": "Lecture Hall Temperature Sensor",
                "sensor_type": "temperature",
                "unit": "°C",
                "status": "active",
                "sampling_interval_seconds": 5,
            },
        ],
    }


@pytest.fixture
def fake_supabase() -> FakeSupabase:
    return FakeSupabase(seed_tables())