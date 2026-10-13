from fastapi import APIRouter

from app.api import activity, analytics, auth, distractions, insights, reports, sessions, settings, tags, ws

api_router = APIRouter(prefix="/api/v1")
for module in (auth, settings, tags, sessions, distractions, activity, analytics, insights, reports, ws):
    api_router.include_router(module.router)
