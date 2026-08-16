from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from CHILE_OEF_* variables."""

    model_config = SettingsConfigDict(
        env_prefix="CHILE_OEF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "postgresql+psycopg://chile_oef:chile_oef@localhost:5432/chile_oef"

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Managed Postgres providers (Render, Heroku-style) hand out
        `postgres://` or plain `postgresql://` connection strings; this
        app's driver is psycopg3, which SQLAlchemy only selects via the
        explicit `postgresql+psycopg://` scheme. Rewriting here means a
        provider's connection string can be used as-is in
        `CHILE_OEF_DATABASE_URL` without a manual edit at deploy time.
        """
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    raw_archive_path: Path = Path("data/raw")
    source_registry_path: Path = Path("config/source-registry.yaml")
    tectonic_registry_path: Path = Path("config/tectonic-assets.yaml")
    tectonic_classifier_path: Path = Path("config/tectonic-classifier.yaml")
    completeness_policy_path: Path = Path("config/completeness-policy.yaml")
    forecast_specification_path: Path = Path("config/forecast-specification.yaml")
    evaluation_protocol_path: Path = Path("config/evaluation-protocol.yaml")
    api_prefix: str = "/v1"
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "https://etemen.cl",
            "https://www.etemen.cl",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )
    log_level: str = "INFO"
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    user_agent: str = "CHILE-OEF/0.1 research-platform"


@lru_cache
def get_settings() -> Settings:
    return Settings()
