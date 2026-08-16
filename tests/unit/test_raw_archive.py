from dataclasses import replace
from datetime import UTC, datetime, timedelta

from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive


def test_archive_is_content_addressed_and_idempotent(tmp_path) -> None:
    artifact = FetchedArtifact(
        source_id="test",
        source_url="https://example.test/data",
        retrieved_at=datetime(2026, 8, 16, tzinfo=UTC),
        content=b"immutable payload",
    )
    archive = RawArchive(tmp_path)

    first = archive.store(artifact, ".bin")
    second = archive.store(
        replace(artifact, retrieved_at=artifact.retrieved_at + timedelta(days=1)),
        ".bin",
    )

    assert first == second
    assert first.byte_length == len(artifact.content)
    assert first.storage_uri.startswith("file:")
    assert len(list(tmp_path.rglob("*.bin"))) == 1
