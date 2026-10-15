from fastapi import APIRouter, HTTPException

from app.repositories.campus_repository import (
    CampusRepository,
)


router = APIRouter(
    prefix="/campus",
    tags=["campus"],
)


@router.get("")
async def get_campus() -> dict:
    try:
        repository = CampusRepository()

        buildings = repository.get_buildings()
        zones = repository.get_zones()
        incidents = repository.get_open_incidents()

        return {
            "success": True,
            "data": {
                "buildings": buildings,
                "zones": zones,
                "incidents": incidents,
            },
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "CAMPUS_FETCH_FAILED",
                "message": str(exc),
            },
        ) from exc