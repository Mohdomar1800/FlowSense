from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.models.user_settings import UserSettings
from app.schemas.settings import SettingsResponse, SettingsUpdate
from app.services.user_settings import get_user_settings, update_user_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
def read_settings(db: DbSession, current_user: CurrentUser) -> UserSettings:
    return get_user_settings(db, current_user)


@router.patch("", response_model=SettingsResponse)
def patch_settings(payload: SettingsUpdate, db: DbSession, current_user: CurrentUser) -> UserSettings:
    return update_user_settings(db, current_user, payload)
