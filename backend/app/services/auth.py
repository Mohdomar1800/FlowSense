from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, ConflictError, UnauthorizedError
from app.core.security import decode_access_token, hash_password, verify_password
from app.core.timeutils import ensure_utc, now_utc
from app.models.user import User
from app.models.user_settings import UserSettings
from app.schemas.auth import UserCreate, UserUpdate
from app.services.analytics import invalidate_productivity_cache

# Compared against when the email is unknown, so failed logins take the same time either way.
_DUMMY_HASH = hash_password("timing-equalizer-password")


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def create_user(db: Session, payload: UserCreate) -> User:
    if get_user_by_email(db, payload.email):
        raise ConflictError("Email is already registered")

    user = User(email=payload.email, hashed_password=hash_password(payload.password), timezone=payload.timezone)
    user.settings = UserSettings()
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:  # concurrent registration with the same email
        db.rollback()
        raise ConflictError("Email is already registered") from exc
    db.refresh(user)
    return user


def user_for_token(db: Session, token: str) -> User:
    """The user a token belongs to. Rejects tokens for deleted users and tokens issued before a password change."""
    claims = decode_access_token(token)
    user = db.get(User, claims.user_id)
    if user is None:
        raise UnauthorizedError("Invalid token")
    if user.password_changed_at is not None and claims.issued_at < ensure_utc(user.password_changed_at):
        raise UnauthorizedError("Your password was changed. Please sign in again.")
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise UnauthorizedError("Invalid email or password")
    if not verify_password(password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")
    return user


def update_user(db: Session, user: User, payload: UserUpdate) -> User:
    timezone_changed = payload.timezone is not None and payload.timezone != user.timezone
    if timezone_changed:
        user.timezone = payload.timezone
    if payload.onboarded is not None:
        user.onboarded_at = (user.onboarded_at or now_utc()) if payload.onboarded else None
    db.commit()
    db.refresh(user)
    if timezone_changed:
        # Day boundaries moved, so cached analytics are no longer valid.
        invalidate_productivity_cache(user.id)
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    """Change the password and sign out every other device (their tokens predate the change)."""
    if not verify_password(current_password, user.hashed_password):
        raise UnauthorizedError("Current password is incorrect")
    if current_password == new_password:
        raise BadRequestError("The new password must be different")
    user.hashed_password = hash_password(new_password)
    # Whole seconds: token "iat" claims have one-second resolution.
    user.password_changed_at = now_utc().replace(microsecond=0)
    db.commit()


def delete_account(db: Session, user: User, password: str) -> None:
    """Permanently delete the user and everything they own (sessions, distractions, reports, rules...)."""
    if not verify_password(password, user.hashed_password):
        raise UnauthorizedError("Password is incorrect")
    user_id = user.id
    db.delete(user)
    db.commit()
    invalidate_productivity_cache(user_id)
