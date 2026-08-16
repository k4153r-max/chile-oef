from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    raw_archive_path: Path = Path("data/raw")
    source_registry_path: Path = Path("config/source-registry.yaml")
    tectonic_registry_path: Path = Path("config/tectonic-assets.yaml")
    tectonic_classifier_path: Path = Path("config/tectonic-classifier.yaml")
    completeness_policy_path: Path = Path("config/completeness-policy.yaml")
    forecast_specification_path: Path = Path("config/forecast-specification.yaml")
    evaluation_protocol_path: Path = Path("config/evaluation-protocol.yaml")
    api_prefix: str = "/v1"
    log_level: str = "INFO"
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    user_agent: str = "CHILE-OEF/0.1 research-platform"


@lru_cache
def get_settings() -> Settings:
    return Settings()
