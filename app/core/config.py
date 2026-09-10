from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AUTOMATION_",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "sqlite:///./automation.db"
    redis_url: str = "redis://localhost:6379/0"
    auth_enabled: bool = False
    oidc_issuer: str = "http://localhost:8080/realms/automation"
    oidc_audience: str = "automation-api"
    webhook_signing_secret: SecretStr | None = None
    max_webhook_body_bytes: int = Field(default=65536, ge=1024, le=1048576)
    log_level: str = "INFO"
    worker_poll_seconds: float = Field(default=1.0, gt=0)
    worker_lease_seconds: int = Field(default=60, ge=10, le=3600)
    scheduler_poll_seconds: float = Field(default=5.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
