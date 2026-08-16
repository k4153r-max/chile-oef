from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from chile_oef.catalog.normalization import NormalizedEvent


@dataclass(frozen=True)
class FetchedArtifact:
    source_id: str
    source_url: str
    retrieved_at: datetime
    content: bytes
    media_type: str | None = None
    http_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)


class EventSourceAdapter(Protocol):
    source_id: str
    parser_version: str

    async def fetch(self) -> FetchedArtifact: ...

    def parse(self, artifact: FetchedArtifact) -> list[NormalizedEvent]: ...
