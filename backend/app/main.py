from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.campus import router as campus_router
from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Backend API for the Smart Campus "
        "Digital Twin."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(campus_router)


@app.get("/")
def root() -> dict:
    return {
        "application": (
            "Smart Campus Digital Twin"
        ),
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "smart-campus-api",
        "version": settings.app_version,
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }
