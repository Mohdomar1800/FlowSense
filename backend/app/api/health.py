from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession
from app.core.cache import get_cache

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/ready")
def readiness_check(db: DbSession) -> JSONResponse:
    """Readiness: the database is reachable. Redis is optional, so it is reported but never fails readiness."""
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except SQLAlchemyError:
        database_ok = False

    body = {
        "status": "ready" if database_ok else "unavailable",
        "database": "ok" if database_ok else "down",
        "cache": "ok" if get_cache().ping() else "unavailable",
    }
    return JSONResponse(status_code=200 if database_ok else 503, content=body)
