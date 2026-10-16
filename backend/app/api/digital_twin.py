"""
Digital twin API (Phase 12).

Feeds the 3D view. Read-only: the twin reports what is true, and
nothing here can change what is true.

An empty campus returns an empty snapshot rather than a 404. A
freshly deployed twin with no zones yet is a working twin, and
treating it as an error would teach a client to special-case a
condition that is not one.
"""

import logging

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.schemas.digital_twin import TwinEntity, TwinSnapshot
from app.services.digital_twin_service import digital_twin_service


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/digital-twin",
    tags=["Digital Twin"],
)


# A twin endpoint failure has nothing to do with the twin's own
# data, so there is no meaningful detail to return. The traceback
# goes to the log.
FAULT_DETAIL = "The digital twin could not be read."


@router.get(
    "/snapshot",
    response_model=TwinSnapshot,
    summary="Every campus entity with its live state",
)
def get_snapshot(
    campus_code: str = Query(default=None),
):
    """
    The whole campus as of one moment.

    Each entity carries its status, its live metrics, the reasons
    behind that status, and any open incident or correlation
    finding, so a client can explain a colour without a second
    request.

    Metrics this deployment does not measure are returned as null
    rather than filled in. A dash is honest; an invented number
    is not.
    """

    try:
        return digital_twin_service.snapshot(
            campus_code=campus_code
        )

    except Exception as exc:
        logger.exception(
            "Failed to build the digital twin snapshot"
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        ) from exc


@router.get(
    "/entities/{entity_id}",
    response_model=TwinEntity,
    summary="One campus entity",
)
def get_entity(entity_id: str):
    """
    A single entity by twin id or zone code.

    Both accepted so a client can use whichever identifier it
    holds.
    """

    try:
        entity = digital_twin_service.entity(entity_id)

        if entity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No campus entity matching '{entity_id}'."
                ),
            )

        return entity

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Failed to read digital twin entity '%s'",
            entity_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        ) from exc