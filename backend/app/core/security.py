from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.timeutils import now_utc


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    issued_at: datetime


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    issued_at = now_utc().replace(microsecond=0)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> TokenClaims:
    """Return the claims of a valid access token, or raise UnauthorizedError."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], options={"require": ["exp", "iat"]}
        )
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc

    subject = payload.get("sub")
    if payload.get("type") != "access" or not subject or not str(subject).isdigit():
        raise UnauthorizedError("Invalid token")
    return TokenClaims(user_id=int(subject), issued_at=datetime.fromtimestamp(payload["iat"], UTC))
