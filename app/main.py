from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.distractions import router as distractions_router
from app.api.health import router as health_router
from app.api.insights import router as insights_router
from app.api.reports import router as reports_router
from app.api.sessions import router as sessions_router
from app.core.config import get_settings
from app.services.scheduler import start_scheduler, stop_scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    version="0.1.0",
    description="FlowSense backend API",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(distractions_router)
app.include_router(analytics_router)
app.include_router(insights_router)
app.include_router(reports_router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"type": "http_error", "message": str(exc.detail)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": {"type": "validation_error", "message": "Request validation failed", "details": exc.errors()}},
    )
