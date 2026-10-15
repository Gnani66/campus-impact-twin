"""
Sensor registry.

Loads the sensors a topic can address, along with the location
chain the topic needs, and caches them. Topics are built and
parsed per message, so this must not hit the database each
time.

Synchronous by design. `app.db.supabase.get_supabase` is a
synchronous, thread-local PostgREST client, so every query here
is synchronous too. When an async MQTT worker is added in a
later stage, `load_registry` must be called off the event loop
(`anyio.to_thread.run_sync` or `asyncio.to_thread`) and the
same applies to any write path, because blocking the loop with
PostgREST calls stalls every other connection on it.

No sensor UUID is hardcoded. They are read from the database,
so the registry is portable across environments.
"""

import threading
from dataclasses import dataclass
from typing import (
    Dict,
    Iterator,
    List,
    Optional,
)
from uuid import UUID

from app.db.supabase import get_supabase
from app.telemetry.models import SEED_METRIC_UNITS


class RegistryError(RuntimeError):
    """
    Raised when the registry cannot be built from what the
    database returned.
    """


class UnknownSensorError(RegistryError):
    """
    Raised when a sensor identifier is not in the registry.
    """


@dataclass(frozen=True)
class SensorEntry:
    """One sensor and the location chain for its topic."""

    sensor_id: UUID
    sensor_code: str
    sensor_type: str
    unit: str
    status: str

    campus_id: UUID
    campus_code: str
    building_id: UUID
    building_code: str
    floor_id: UUID
    floor_code: str
    zone_id: UUID
    zone_code: str

    equipment_id: Optional[UUID] = None
    equipment_code: Optional[str] = None
    sampling_interval_seconds: Optional[int] = None

    # Zone and equipment attributes the simulator needs. Added
    # for Phase 5 Stage 4; optional so existing callers and
    # fixtures are unaffected when a zone has no such values.
    zone_capacity: Optional[int] = None
    zone_area_sq_meters: Optional[float] = None
    zone_schedule_start_hour: Optional[int] = None
    zone_schedule_end_hour: Optional[int] = None
    equipment_rated_power_kw: Optional[float] = None

    @property
    def metric(self) -> str:
        """
        The telemetry metric for this sensor. The seeded
        sensors report their sensor type directly, e.g.
        `temperature`, so no mapping table is needed.
        """

        return self.sensor_type


def _as_uuid(
    value: object,
    label: str,
) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise RegistryError(
            f"{label} is not a valid uuid: {value!r}"
        ) from None


def _index_by(
    rows: List[dict],
    key: str,
    label: str,
) -> Dict[str, dict]:
    indexed: Dict[str, dict] = {}

    for row in rows:
        if key not in row or row[key] is None:
            raise RegistryError(
                f"{label} row is missing '{key}'"
            )

        identifier = str(row[key])

        if identifier in indexed:
            raise RegistryError(
                f"duplicate {label} '{identifier}'"
            )

        indexed[identifier] = row

    return indexed


class SensorRegistry:
    """
    Read-only set of active sensors, indexed by UUID and by
    sensor code.
    """

    def __init__(self, entries: List[SensorEntry]) -> None:
        if not entries:
            raise RegistryError(
                "registry is empty; no active sensors found"
            )

        self._entries = list(entries)
        self._by_id: Dict[UUID, SensorEntry] = {}
        self._by_code: Dict[str, SensorEntry] = {}

        for entry in self._entries:
            if entry.sensor_id in self._by_id:
                raise RegistryError(
                    "duplicate sensor id "
                    f"'{entry.sensor_id}'"
                )

            if entry.sensor_code in self._by_code:
                raise RegistryError(
                    "duplicate sensor code "
                    f"'{entry.sensor_code}'"
                )

            self._by_id[entry.sensor_id] = entry
            self._by_code[entry.sensor_code] = entry

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[SensorEntry]:
        return iter(self._entries)

    @property
    def entries(self) -> List[SensorEntry]:
        return list(self._entries)

    @property
    def sensor_codes(self) -> List[str]:
        return [
            entry.sensor_code
            for entry in self._entries
        ]

    def get_by_id(
        self,
        sensor_id: UUID,
    ) -> SensorEntry:
        entry = self._by_id.get(sensor_id)

        if entry is None:
            raise UnknownSensorError(
                f"unknown sensor id '{sensor_id}'"
            )

        return entry

    def get_by_code(
        self,
        sensor_code: str,
    ) -> SensorEntry:
        entry = self._by_code.get(sensor_code)

        if entry is None:
            raise UnknownSensorError(
                f"unknown sensor code '{sensor_code}'"
            )

        return entry

    def has(self, sensor_id: UUID) -> bool:
        return sensor_id in self._by_id


def load_registry(client: object = None) -> SensorRegistry:
    """
    Builds the registry from Supabase.

    Uses explicit joins rather than PostgREST embedded
    selects, matching `app.api.campus._select_all`: the
    embedded key names depend on relationship metadata, and
    this runs once at startup, so six small queries are
    cheaper than being wrong about them.

    `client` is injectable so tests can supply a fake.
    """

    supabase = client if client is not None else get_supabase()

    def fetch(
        table: str,
        columns: str,
        **filters: object,
    ) -> List[dict]:
        query = supabase.table(table).select(columns)

        for column, value in filters.items():
            query = query.eq(column, value)

        return query.execute().data or []

    campuses = _index_by(
        fetch("campuses", "id, code"),
        "id",
        "campus",
    )

    buildings = _index_by(
        fetch("buildings", "id, campus_id, code"),
        "id",
        "building",
    )

    floors = _index_by(
        fetch("floors", "id, building_id, code"),
        "id",
        "floor",
    )

    zones = _index_by(
        fetch(
            "zones",
            (
                "id, floor_id, code, capacity, "
                "area_sq_meters, schedule_start_hour, "
                "schedule_end_hour"
            ),
        ),
        "id",
        "zone",
    )

    equipment = _index_by(
        fetch("equipment", "id, code, rated_power_kw"),
        "id",
        "equipment",
    )

    sensors = fetch(
        "sensors",
        (
            "id, zone_id, equipment_id, code, name, "
            "sensor_type, unit, status, "
            "sampling_interval_seconds"
        ),
        status="active",
    )

    entries: List[SensorEntry] = []
    seen_codes = set()

    for sensor in sensors:
        sensor_id = _as_uuid(sensor.get("id"), "sensor id")
        sensor_code = str(sensor.get("code") or "")

        if not sensor_code:
            raise RegistryError(
                f"sensor '{sensor_id}' has no code"
            )

        if sensor_code in seen_codes:
            raise RegistryError(
                f"duplicate sensor code '{sensor_code}'"
            )

        seen_codes.add(sensor_code)

        zone_id = sensor.get("zone_id")
        zone = zones.get(str(zone_id))

        if zone is None:
            raise RegistryError(
                f"sensor '{sensor_code}' references "
                f"unknown zone '{zone_id}'"
            )

        floor = floors.get(str(zone["floor_id"]))

        if floor is None:
            raise RegistryError(
                f"zone '{zone['code']}' references unknown "
                f"floor '{zone['floor_id']}'"
            )

        building = buildings.get(
            str(floor["building_id"])
        )

        if building is None:
            raise RegistryError(
                f"floor '{floor['code']}' references unknown "
                f"building '{floor['building_id']}'"
            )

        campus = campuses.get(
            str(building["campus_id"])
        )

        if campus is None:
            raise RegistryError(
                f"building '{building['code']}' references "
                f"unknown campus '{building['campus_id']}'"
            )

        sensor_type = str(sensor.get("sensor_type") or "")

        if sensor_type not in SEED_METRIC_UNITS:
            raise RegistryError(
                f"sensor '{sensor_code}' has unsupported "
                f"sensor_type '{sensor_type}'; expected one "
                f"of {sorted(SEED_METRIC_UNITS)}"
            )

        unit = str(sensor.get("unit") or "")

        if unit not in SEED_METRIC_UNITS[sensor_type]:
            raise RegistryError(
                f"sensor '{sensor_code}' reports unit "
                f"'{unit}', which is not valid for "
                f"'{sensor_type}'"
            )

        equipment_id = sensor.get("equipment_id")
        equipment_row = equipment.get(str(equipment_id))

        if equipment_id is not None and equipment_row is None:
            raise RegistryError(
                f"sensor '{sensor_code}' references unknown "
                f"equipment '{equipment_id}'"
            )

        entries.append(
            SensorEntry(
                sensor_id=sensor_id,
                sensor_code=sensor_code,
                sensor_type=sensor_type,
                unit=unit,
                status=str(sensor.get("status") or ""),
                campus_id=_as_uuid(campus["id"], "campus id"),
                campus_code=str(campus["code"]),
                building_id=_as_uuid(
                    building["id"], "building id"
                ),
                building_code=str(building["code"]),
                floor_id=_as_uuid(floor["id"], "floor id"),
                floor_code=str(floor["code"]),
                zone_id=_as_uuid(zone["id"], "zone id"),
                zone_code=str(zone["code"]),
                equipment_id=(
                    _as_uuid(equipment_row["id"], "equipment id")
                    if equipment_row is not None
                    else None
                ),
                equipment_code=(
                    str(equipment_row["code"])
                    if equipment_row is not None
                    else None
                ),
                sampling_interval_seconds=sensor.get(
                    "sampling_interval_seconds"
                ),
                zone_capacity=zone.get("capacity"),
                zone_area_sq_meters=zone.get("area_sq_meters"),
                zone_schedule_start_hour=zone.get(
                    "schedule_start_hour"
                ),
                zone_schedule_end_hour=zone.get(
                    "schedule_end_hour"
                ),
                equipment_rated_power_kw=(
                    equipment_row.get("rated_power_kw")
                    if equipment_row is not None
                    else None
                ),
            )
        )

    return SensorRegistry(entries)


_registry: Optional[SensorRegistry] = None
_registry_lock = threading.Lock()


def get_registry(
    force_refresh: bool = False,
) -> SensorRegistry:
    """
    Returns the cached registry, loading it on first use.
    """

    global _registry

    with _registry_lock:
        if _registry is None or force_refresh:
            _registry = load_registry()

        return _registry


def reset_registry() -> None:
    """
    Drops the cache. For tests and forced reloads.
    """

    global _registry

    with _registry_lock:
        _registry = None