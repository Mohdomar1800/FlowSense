import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError, TooManyRequestsError
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _error(status_code: int, error_type: str, message: str, details=None) -> JSONResponse:
    body: dict = {"type": error_type, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status_code, content={"error": body})


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.scheduler_enabled:
            start_scheduler()
        try:
            yield
        finally:
            stop_scheduler()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.app_debug,
        version="1.0.0",
        description="FlowSense backend API",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(api_router)

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        response = _error(exc.status_code, exc.error_type, exc.message)
        if exc.status_code == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        if isinstance(exc, TooManyRequestsError):
            response.headers["Retry-After"] = str(exc.retry_after)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "validation_error", "Request validation failed", jsonable_encoder(exc.errors()))

    # Mounted last so API routes always win. Serving the UI from the same origin avoids CORS for HTTP and WebSocket.
    if settings.frontend_dir and settings.frontend_dir.is_dir():
        app.mount("/", NoCacheStaticFiles(directory=settings.frontend_dir, html=True), name="frontend")

    return app


class NoCacheStaticFiles(StaticFiles):
    """UI files change with each app update and are tiny; always revalidate so an update is never half-applied."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = create_app()
