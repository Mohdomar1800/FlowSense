from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness_check() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ready",
        "environment": settings.app_env,
        "database_url": settings.database_url,
        "redis_url": settings.redis_url,
    }
