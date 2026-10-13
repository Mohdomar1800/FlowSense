from sqlalchemy.orm import Session

from app.core.events import publish_user_event
from app.models.user import User
from app.models.user_settings import UserSettings
from app.schemas.settings import SettingsResponse, SettingsUpdate
from app.services.analytics import invalidate_productivity_cache


def get_user_settings(db: Session, user: User) -> UserSettings:
    settings = db.get(UserSettings, user.id)
    if settings is None:
        # Users created before settings existed get defaults on first access.
        settings = UserSettings(user_id=user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_user_settings(db: Session, user: User, payload: SettingsUpdate) -> UserSettings:
    settings = get_user_settings(db, user)
    for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    invalidate_productivity_cache(user.id)  # dashboards show "goal met" per day
    # The desktop agent listens for this, e.g. to stop screen tracking the moment it's switched off.
    payload = SettingsResponse.model_validate(settings).model_dump(mode="json")
    publish_user_event(user.id, "settings.updated", {"settings": payload})
    return settings
