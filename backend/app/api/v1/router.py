from fastapi import APIRouter

from app.api.v1.campus import router as campus_router
from app.api.v1.health import router as health_router


api_router = APIRouter(
    prefix="/api/v1",
)

api_router.include_router(
    health_router,
)

api_router.include_router(
    campus_router,
)