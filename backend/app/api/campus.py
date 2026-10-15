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
    SensorResponse,
    ZoneResponse,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/campus",
    tags=["Campus"],
)


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
                f"'{campus_code}': {exc}"
            ),
        ) from exc
