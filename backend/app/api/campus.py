from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.db.supabase import get_supabase
from app.schemas.campus import (
    BuildingResponse,
    CampusResponse,
    CampusTwinResponse,
    EquipmentResponse,
    FloorResponse,
    IncidentResponse,
    LatestTelemetryReadingResponse,
    LatestTelemetryResponse,
    SensorResponse,
    ZoneResponse,
)
from app.telemetry.registry import get_registry


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/campus",
    tags=["Campus"],
)


# Guards the response size and the size of the single query
# that backs it. The table grows by five rows every telemetry
# tick, so an unbounded scan would get slower forever.
MAX_SENSORS_PER_RESPONSE = 200
MAX_ROWS_SCANNED = 500


def _latest_readings_for_sensors(
    sensor_ids: List[str],
    zone_ids: List[str],
    campus_ids: List[str],
    max_rows_scanned: int = MAX_ROWS_SCANNED,
) -> List[Dict[str, Any]]:
    """
    Fetches recent telemetry rows for the given sensors.

    PostgREST cannot express `DISTINCT ON (sensor_id)`, so one
    bounded scan is ordered newest first and reduced to the
    first row per sensor by the caller. `id` breaks ties when
    two rows share a timestamp, which keeps the result
    deterministic for identical input.
    """

    client = get_supabase()

    query = (
        client.table("telemetry_readings")
        .select("*")
        .in_("sensor_id", sensor_ids)
        .order("timestamp", desc=True)
        .order("id", desc=True)
        .limit(max_rows_scanned)
    )

    if zone_ids:
        # Defence in depth: never let a row outside the
        # requested zone leak in through the sensor filter.
        query = query.in_("zone_id", zone_ids)

    if campus_ids:
        # A sensor id alone does not prove a row belongs to
        # this campus, so the campus is constrained too.
        query = query.in_("campus_id", campus_ids)

    return query.execute().data or []


def _select_all(
    table: str,
    filters: Optional[Dict[str, Any]] = None,
    order_column: Optional[str] = None,
    descending: bool = False,
) -> List[Dict[str, Any]]:
    """
    Runs a select against Supabase.

    `filters` maps a column name to either a single value
    or a list of values. When the value list is empty the
    table cannot contain matching rows, so an empty list is
    returned without hitting the database.
    """

    if not filters:
        return []

    query = get_supabase().table(table).select("*")

    for column, value in filters.items():
        if isinstance(value, (list, tuple, set)):
            values = list(value)

            if not values:
                return []

            query = query.in_(column, values)

        else:
            query = query.eq(column, value)

    if order_column:
        query = query.order(
            order_column,
            desc=descending,
        )

    return query.execute().data


@router.get(
    "/{campus_code}/twin",
    response_model=CampusTwinResponse,
    summary="Complete digital twin entity graph for a campus",
)
def get_campus_twin(
    campus_code: str,
) -> CampusTwinResponse:
    try:
        campus_result = (
            get_supabase()
            .table("campuses")
            .select("*")
            .eq("code", campus_code)
            .limit(1)
            .execute()
            .data
        )

        if not campus_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Campus '{campus_code}' not found."
                ),
            )

        campus = campus_result[0]
        campus_id = campus["id"]

        buildings = _select_all(
            "buildings",
            {"campus_id": campus_id},
            order_column="code",
        )

        floors = _select_all(
            "floors",
            {
                "building_id": [
                    building["id"]
                    for building in buildings
                ]
            },
            order_column="floor_number",
        )

        zones = _select_all(
            "zones",
            {
                "floor_id": [
                    floor["id"] for floor in floors
                ]
            },
            order_column="code",
        )

        zone_ids = [zone["id"] for zone in zones]

        equipment = _select_all(
            "equipment",
            {"zone_id": zone_ids},
            order_column="code",
        )

        sensors = _select_all(
            "sensors",
            {"zone_id": zone_ids},
            order_column="code",
        )

        incidents = _select_all(
            "incidents",
            {"campus_id": campus_id},
            order_column="impact_score",
            descending=True,
        )

        return CampusTwinResponse(
            campus=CampusResponse(**campus),
            buildings=[
                BuildingResponse(**building)
                for building in buildings
            ],
            floors=[
                FloorResponse(**floor)
                for floor in floors
            ],
            zones=[
                ZoneResponse(**zone)
                for zone in zones
            ],
            equipment=[
                EquipmentResponse(**item)
                for item in equipment
            ],
            sensors=[
                SensorResponse(**sensor)
                for sensor in sensors
            ],
            incidents=[
                IncidentResponse(**incident)
                for incident in incidents
            ],
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Failed to load campus twin for '%s'",
            campus_code,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Failed to load campus twin for "
                f"'{campus_code}'."
            ),
        ) from exc


@router.get(
    "/{campus_code}/telemetry/latest",
    response_model=LatestTelemetryResponse,
    summary="Latest stored telemetry reading per sensor",
)
def get_latest_telemetry(
    campus_code: str,
    zone: Optional[str] = Query(
        default=None,
        description=(
            "Optional zone code. Only readings for that "
            "zone are returned."
        ),
    ),
    limit: int = Query(
        default=MAX_SENSORS_PER_RESPONSE,
        ge=1,
        le=MAX_SENSORS_PER_RESPONSE,
        description=(
            "Maximum number of readings returned, sorted "
            "by metric then sensor id."
        ),
    ),
) -> LatestTelemetryResponse:
    """
    Reads the newest stored reading for each registered sensor.

    Strictly read-only: the only statement issued is a single
    bounded select. Database errors are reported without the
    underlying exception text, so connection details or
    credentials cannot leak through the API.
    """

    try:
        campus = _select_all(
            "campuses", {"code": campus_code}
        )

        if not campus:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Campus '{campus_code}' not found."
                ),
            )

        campus = campus[0]

        registry = get_registry()

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Failed to resolve sensors for campus '%s'",
            campus_code,
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Telemetry is unavailable: the sensor "
                "registry could not be loaded."
            ),
        ) from None

    entries = [
        entry
        for entry in registry
        if entry.campus_code == campus_code
    ]

    zone_codes = {
        entry.zone_code for entry in entries
    }

    if zone is not None and zone not in zone_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown zone '{zone}' for campus "
                f"'{campus_code}'."
            ),
        )

    if zone is not None:
        entries = [
            entry
            for entry in entries
            if entry.zone_code == zone
        ]

    entries = entries[:MAX_SENSORS_PER_RESPONSE]

    sensor_ids = [str(entry.sensor_id) for entry in entries]
    zone_ids = [
        str(entry.zone_id) for entry in entries
    ]

    # No sensors in scope: an empty result, not an error.
    if not sensor_ids:
        return LatestTelemetryResponse(
            campus_code=campus_code,
            campus_id=campus["id"],
            zone_code=zone,
            sensors_considered=0,
            reading_count=0,
            readings=[],
            sensors_without_readings=[],
            generated_at=datetime.now(timezone.utc),
        )

    try:
        rows = _latest_readings_for_sensors(
            sensor_ids, zone_ids, [str(campus["id"])]
        )

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Failed to read latest telemetry for '%s'",
            campus_code,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Failed to read latest telemetry for "
                f"'{campus_code}'."
            ),
        ) from None

    # Keyed by the string form, which is how the stored row
    # identifies the sensor.
    by_id = {
        str(entry.sensor_id): entry for entry in entries
    }

    # Rows arrive newest first, so the first hit per sensor is
    # the latest one.
    latest: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        sensor_id = row.get("sensor_id")

        if sensor_id is None:
            continue

        key = str(sensor_id)

        if key in by_id and key not in latest:
            latest[key] = row

    readings = []

    for entry in entries:
        row = latest.get(str(entry.sensor_id))

        if row is None:
            continue

        readings.append(
            LatestTelemetryReadingResponse(
                sensor_id=str(entry.sensor_id),
                sensor_code=entry.sensor_code,
                sensor_type=entry.sensor_type,
                metric=row["metric"],
                value=row["value"],
                unit=row["unit"],
                timestamp=row["timestamp"],
                source=row["source"],
                quality=row["quality"],
                campus_id=row.get("campus_id"),
                building_id=row.get("building_id"),
                floor_id=row.get("floor_id"),
                zone_id=row.get("zone_id"),
                campus_code=entry.campus_code,
                building_code=entry.building_code,
                floor_code=entry.floor_code,
                zone_code=entry.zone_code,
                metadata=row.get("metadata") or {},
            )
        )

    # Deterministic order regardless of scan order.
    readings.sort(key=lambda item: (item.metric, item.sensor_id))

    readings = readings[:limit]

    reported = {item.sensor_id for item in readings}

    without = sorted(
        entry.sensor_code
        for entry in entries
        if str(entry.sensor_id) not in reported
    )

    return LatestTelemetryResponse(
        campus_code=campus_code,
        campus_id=campus["id"],
        zone_code=zone,
        sensors_considered=len(entries),
        reading_count=len(readings),
        readings=readings,
        sensors_without_readings=without,
        generated_at=datetime.now(timezone.utc),
    )
