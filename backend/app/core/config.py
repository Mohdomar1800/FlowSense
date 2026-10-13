from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "change-me-in-env"


class Settings(BaseSettings):
    app_name: str = "FlowSense"
    app_env: str = "development"
    app_debug: bool = False

    postgres_db: str = "flowsense"
    postgres_user: str = "flowsense"
    postgres_password: str = "flowsense"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    # Full URL override (used by tests and hosted deployments). Takes precedence over the POSTGRES_* parts.
    database_url_override: str | None = None

    redis_enabled: bool = True
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    analytics_cache_ttl_seconds: int = 300

    jwt_secret_key: str = INSECURE_DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    # 7 days, renewed while the app is in use. Changing the password revokes older tokens (see services.auth).
    jwt_expire_minutes: int = 60 * 24 * 7
    # bcrypt work factor. 12 is the secure default; tests lower it for speed.
    bcrypt_rounds: int = 12

    scheduler_enabled: bool = True
    cors_origins: list[str] = ["http://localhost", "http://127.0.0.1"]
    # Directory with the web UI, served at "/". Defaults to the repo's frontend/ folder; unset or missing = API only.
    frontend_dir: Path | None = Path(__file__).resolve().parents[3] / "frontend"

    # The repo-root .env is shared with docker compose; a backend/.env (if present) overrides it.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    @model_validator(mode="after")
    def _refuse_insecure_production(self) -> "Settings":
        if self.app_env == "production" and self.jwt_secret_key == INSECURE_DEFAULT_SECRET:
            raise ValueError("JWT_SECRET_KEY must be set to a strong secret in production")
        return self

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
