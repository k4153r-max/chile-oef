from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class EndpointRegistration(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str
    url: str | None = None
    url_template: str | None = None
    formats: list[str] = Field(default_factory=list)


class SourceRegistration(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    authority: str
    role: str
    endpoints: list[EndpointRegistration]
    license: str
    attribution: str | None = None
    stability: str
    enabled: bool


class SourceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    reviewed_at: datetime
    sources: list[SourceRegistration]

    def by_id(self, source_id: str) -> SourceRegistration:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError(source_id)


def load_source_registry(path: Path) -> SourceRegistry:
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SourceRegistry.model_validate(document)
