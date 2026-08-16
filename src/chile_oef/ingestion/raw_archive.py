import hashlib
from dataclasses import dataclass
from pathlib import Path

from chile_oef.ingestion.base import FetchedArtifact


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    storage_uri: str
    byte_length: int


class RawArchive:
    """Content-addressed raw archive; writes never overwrite existing content."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def store(self, artifact: FetchedArtifact, suffix: str = ".bin") -> StoredArtifact:
        digest = hashlib.sha256(artifact.content).hexdigest()
        path = self.root / artifact.source_id / digest[:2] / digest[2:4] / f"{digest}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(artifact.content)
            temporary.replace(path)
        return StoredArtifact(
            sha256=digest,
            storage_uri=path.resolve().as_uri(),
            byte_length=len(artifact.content),
        )
