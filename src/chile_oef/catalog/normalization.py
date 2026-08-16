import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


class NormalizedEvent(BaseModel):
    """Lossless-enough normalized projection of one source event revision."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)
    source_event_id: str = Field(min_length=1, max_length=255)
    event_time: datetime
    source_updated_at: datetime | None = None
    received_at: datetime
    available_at: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    depth_km: float | None = None
    magnitude: float | None = None
    magnitude_type: str | None = None
    place: str | None = None
    status: str | None = None
    location_uncertainty_km: float | None = Field(default=None, ge=0)
    depth_uncertainty_km: float | None = Field(default=None, ge=0)
    magnitude_uncertainty: float | None = Field(default=None, ge=0)
    source_payload: dict[str, Any]
    parser_version: str

    @field_validator("event_time", "source_updated_at", "received_at", "available_at", mode="after")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_aware_utc(value)

    @field_validator("magnitude_type", mode="before")
    @classmethod
    def normalize_magnitude_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

    @model_validator(mode="after")
    def availability_is_not_before_receipt(self) -> "NormalizedEvent":
        if self.available_at < self.received_at:
            raise ValueError("available_at cannot precede received_at")
        return self

    def revision_document(self) -> dict[str, Any]:
        """Stable scientific fields used to detect a source-side revision."""

        return {
            "source_id": self.source_id,
            "source_event_id": self.source_event_id,
            "event_time": self.event_time.isoformat(),
            "source_updated_at": (
                self.source_updated_at.isoformat() if self.source_updated_at else None
            ),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "depth_km": self.depth_km,
            "magnitude": self.magnitude,
            "magnitude_type": self.magnitude_type,
            "place": self.place,
            "status": self.status,
            "location_uncertainty_km": self.location_uncertainty_km,
            "depth_uncertainty_km": self.depth_uncertainty_km,
            "magnitude_uncertainty": self.magnitude_uncertainty,
            "source_payload": self.source_payload,
            "parser_version": self.parser_version,
        }

    @property
    def revision_hash(self) -> str:
        encoded = json.dumps(
            self.revision_document(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
