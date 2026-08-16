import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import orjson
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chile_oef.db.models import (
    DatasetArtifact,
    DatasetEventRevision,
    DatasetVersion,
    EventRevision,
    RawArtifact,
    SourceEvent,
)


def manifest_digest(manifest: dict[str, Any]) -> str:
    payload = orjson.dumps(manifest, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(payload).hexdigest()


class DatasetVersionService:
    """Create an immutable catalog snapshot from knowledge available at `as_of`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        dataset_id: str,
        version: str,
        as_of: datetime,
        git_commit: str | None = None,
        created_at: datetime | None = None,
    ) -> DatasetVersion:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not dataset_id.strip() or not version.strip():
            raise ValueError("dataset_id and version must not be blank")
        as_of = as_of.astimezone(UTC)
        created_at = (created_at or datetime.now(UTC)).astimezone(UTC)
        existing = self.session.scalar(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset_id,
                DatasetVersion.version == version,
            )
        )
        if existing is not None:
            raise ValueError(f"dataset version {dataset_id}/{version} already exists")

        selections = self._latest_revisions(as_of)
        artifact_by_id = {artifact.id: artifact for _, _, artifact in selections}
        manifest = {
            "dataset_id": dataset_id,
            "version": version,
            "created_at": created_at.isoformat(),
            "as_of": as_of.isoformat(),
            "sources": sorted({source.source_id for _, source, _ in selections}),
            "artifacts": [
                {
                    "id": str(artifact.id),
                    "sha256": artifact.sha256,
                    "uri": artifact.storage_uri,
                    "byte_length": artifact.byte_length,
                }
                for artifact in sorted(artifact_by_id.values(), key=lambda item: str(item.id))
            ],
            "event_revisions": [
                {
                    "id": str(revision.id),
                    "source_id": source.source_id,
                    "source_event_id": source.source_event_id,
                    "revision_hash": revision.revision_hash,
                    "available_at": revision.available_at.isoformat(),
                }
                for revision, source, _ in selections
            ],
            "selection": {
                "rule": "latest revision per source event with available_at <= as_of",
                "time_axis": "available_at",
            },
            "git_commit": git_commit,
        }
        dataset = DatasetVersion(
            id=uuid.uuid4(),
            dataset_id=dataset_id,
            version=version,
            as_of=as_of,
            created_at=created_at,
            manifest_sha256=manifest_digest(manifest),
            manifest_json=manifest,
            git_commit=git_commit,
        )
        self.session.add(dataset)
        self.session.flush()
        self.session.add_all(
            DatasetArtifact(dataset_version_id=dataset.id, raw_artifact_id=artifact_id)
            for artifact_id in artifact_by_id
        )
        self.session.add_all(
            DatasetEventRevision(
                dataset_version_id=dataset.id,
                event_revision_id=revision.id,
            )
            for revision, _, _ in selections
        )
        self.session.commit()
        return dataset

    def _latest_revisions(
        self, as_of: datetime
    ) -> list[tuple[EventRevision, SourceEvent, RawArtifact]]:
        ranked = (
            select(
                EventRevision.id.label("revision_id"),
                func.row_number()
                .over(
                    partition_by=EventRevision.source_event_id,
                    order_by=(
                        EventRevision.available_at.desc(),
                        EventRevision.recorded_at.desc(),
                    ),
                )
                .label("revision_rank"),
            )
            .where(EventRevision.available_at <= as_of)
            .subquery()
        )
        statement = (
            select(EventRevision, SourceEvent, RawArtifact)
            .join(ranked, ranked.c.revision_id == EventRevision.id)
            .join(SourceEvent, SourceEvent.id == EventRevision.source_event_id)
            .join(RawArtifact, RawArtifact.id == EventRevision.raw_artifact_id)
            .where(ranked.c.revision_rank == 1)
            .order_by(SourceEvent.source_id, SourceEvent.source_event_id, EventRevision.id)
        )
        return list(self.session.execute(statement).tuples())
