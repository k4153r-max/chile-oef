from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TectonicAssetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    filename: str
    url: str
    byte_length: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class TectonicReleaseSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source_id: str
    release_id: str
    title: str
    doi: str
    license: str
    parser: str
    assets: list[TectonicAssetSpec]

    @model_validator(mode="after")
    def asset_types_are_unique(self) -> "TectonicReleaseSpec":
        asset_types = [asset.type for asset in self.assets]
        if len(asset_types) != len(set(asset_types)):
            raise ValueError("tectonic asset types must be unique within a release")
        return self

    def asset(self, asset_type: str) -> TectonicAssetSpec:
        matches = [item for item in self.assets if item.type == asset_type]
        if len(matches) != 1:
            raise KeyError(f"release {self.id!r} has no unique asset {asset_type!r}")
        return matches[0]


class TectonicRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    reviewed_at: datetime
    releases: list[TectonicReleaseSpec]

    @model_validator(mode="after")
    def release_ids_are_unique(self) -> "TectonicRegistry":
        release_ids = [release.id for release in self.releases]
        if len(release_ids) != len(set(release_ids)):
            raise ValueError("tectonic registry release IDs must be unique")
        return self

    def by_id(self, release_id: str) -> TectonicReleaseSpec:
        matches = [item for item in self.releases if item.id == release_id]
        if len(matches) != 1:
            raise KeyError(f"unknown or duplicated tectonic release {release_id!r}")
        return matches[0]


def load_tectonic_registry(path: Path) -> TectonicRegistry:
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TectonicRegistry.model_validate(document)
