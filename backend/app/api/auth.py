from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import TooManyRequestsError, UnauthorizedError
from app.core.ratelimit import login_limiter
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import (
    AccountDeletion,
    PasswordChange,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from app.services.auth import authenticate_user, change_password, create_user, delete_account, update_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_for(user: User) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(user.id), expires_in=get_settings().jwt_expire_minutes * 60)


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: UserCreate, db: DbSession) -> User:
    return create_user(db, payload)


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, request: Request, db: DbSession) -> TokenResponse:
    # Per account and client address: slows password guessing without letting others lock you out remotely.
    key = f"{payload.email}|{request.client.host if request.client else 'unknown'}"
    if wait := login_limiter.retry_after(key):
        raise TooManyRequestsError(f"Too many failed sign-in attempts. Try again in {max(1, wait // 60)} min.", wait)
    try:
        user = authenticate_user(db, payload.email, payload.password)
    except UnauthorizedError:
        login_limiter.record_failure(key)
        raise
    login_limiter.reset(key)
    return _token_for(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(current_user: CurrentUser) -> TokenResponse:
    """Exchange a still-valid token for a fresh one, so active users stay signed in."""
    return _token_for(current_user)


@router.get("/me", response_model=UserResponse)
def read_me(current_user: CurrentUser) -> User:
    return current_user


@router.patch("/me", response_model=UserResponse)
def update_me(payload: UserUpdate, db: DbSession, current_user: CurrentUser) -> User:
    return update_user(db, current_user, payload)


@router.post("/password", response_model=TokenResponse)
def update_password(payload: PasswordChange, db: DbSession, current_user: CurrentUser) -> TokenResponse:
    """Change the password. Other devices are signed out; this one gets a new token."""
    change_password(db, current_user, payload.current_password, payload.new_password)
    return _token_for(current_user)


@router.delete("/me", status_code=204)
def delete_me(payload: AccountDeletion, db: DbSession, current_user: CurrentUser) -> Response:
    """Permanently delete the account and all of its data."""
    delete_account(db, current_user, payload.password)
    return Response(status_code=204)
