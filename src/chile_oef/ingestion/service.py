import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from geoalchemy2.elements import WKTElement
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from chile_oef.catalog.deduplication import (
    DeduplicationScorer,
    EventFingerprint,
)
from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.db.models import (
    CanonicalEvent,
    CanonicalEventMembership,
    CatalogSource,
    DataQualityLog,
    DeduplicationCandidate,
    EventRevision,
    IngestionArtifact,
    IngestionRun,
    RawArtifact,
    SourceEndpoint,
    SourceEvent,
)
from chile_oef.ingestion.base import EventSourceAdapter, FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import SourceRegistry
from chile_oef.quality.validators import evaluate_event_quality


@dataclass(frozen=True)
class IngestionResult:
    run_id: uuid.UUID
    records_seen: int
    revisions_inserted: int
    artifacts_inserted: int


def sync_source_registry(session: Session, registry: SourceRegistry) -> None:
    """Insert or update administrative source metadata from reviewed configuration."""

    for item in registry.sources:
        source = session.get(CatalogSource, item.id)
        metadata = item.model_dump(exclude={"endpoints"})
        if source is None:
            source = CatalogSource(
                id=item.id,
                authority=item.authority,
                role=item.role,
                license_id=item.license,
                attribution=item.attribution,
                enabled=item.enabled,
                metadata_json=metadata,
            )
            session.add(source)
        else:
            source.authority = item.authority
            source.role = item.role
            source.license_id = item.license
            source.attribution = item.attribution
            source.enabled = item.enabled
            source.metadata_json = metadata
        for endpoint in item.endpoints:
            url = endpoint.url or endpoint.url_template
            if url is None:
                continue
            existing = session.scalar(
                select(SourceEndpoint).where(
                    SourceEndpoint.source_id == item.id,
                    SourceEndpoint.kind == endpoint.kind,
                    SourceEndpoint.url == url,
                )
            )
            if existing is None:
                session.add(
                    SourceEndpoint(
                        source_id=item.id,
                        kind=endpoint.kind,
                        url=url,
                        enabled=item.enabled,
                        metadata_json=endpoint.model_dump(),
                    )
                )
            else:
                existing.enabled = item.enabled
                existing.metadata_json = endpoint.model_dump()
    session.commit()


class IngestionService:
    def __init__(
        self,
        session: Session,
        raw_archive: RawArchive,
        *,
        deduplication_scorer: DeduplicationScorer | None = None,
    ) -> None:
        self.session = session
        self.raw_archive = raw_archive
        self.scorer = deduplication_scorer or DeduplicationScorer()

    async def run(self, adapter: EventSourceAdapter) -> IngestionResult:
        source = self.session.get(CatalogSource, adapter.source_id)
        if source is None:
            raise ValueError(f"source {adapter.source_id!r} is not registered")
        initial_url = str(
            getattr(adapter, "url", None)
            or getattr(adapter, "query_url", None)
            or f"source:{adapter.source_id}"
        )
        run = IngestionRun(source_id=adapter.source_id, request_url=initial_url)
        self.session.add(run)
        self.session.commit()
        run_id = run.id
        try:
            artifact = await adapter.fetch()
            run.request_url = artifact.source_url
            result = self.ingest_artifact(adapter, artifact, run)
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
            run.records_seen = result.records_seen
            run.revisions_inserted = result.revisions_inserted
            self.session.commit()
            return result
        except Exception as exc:
            self.session.rollback()
            run = self.session.get(IngestionRun, run_id)
            if run is not None:
                run.status = "failed"
                run.finished_at = datetime.now(UTC)
                run.error_message = str(exc)[:4000]
                self.session.commit()
            raise

    def ingest_artifact(
        self,
        adapter: EventSourceAdapter,
        artifact: FetchedArtifact,
        run: IngestionRun,
    ) -> IngestionResult:
        suffix = self._suffix_for(artifact.media_type)
        stored = self.raw_archive.store(artifact, suffix=suffix)
        raw_row = self.session.scalar(
            select(RawArtifact).where(
                RawArtifact.source_id == artifact.source_id,
                RawArtifact.sha256 == stored.sha256,
            )
        )
        artifacts_inserted = 0
        if raw_row is None:
            raw_row = RawArtifact(
                source_id=artifact.source_id,
                retrieved_at=artifact.retrieved_at,
                source_url=artifact.source_url,
                storage_uri=stored.storage_uri,
                sha256=stored.sha256,
                byte_length=stored.byte_length,
                media_type=artifact.media_type,
                http_status=artifact.http_status,
                response_headers=artifact.response_headers,
            )
            self.session.add(raw_row)
            self.session.flush()
            artifacts_inserted = 1
        run_artifact = self.session.scalar(
            select(IngestionArtifact).where(
                IngestionArtifact.ingestion_run_id == run.id,
                IngestionArtifact.raw_artifact_id == raw_row.id,
            )
        )
        if run_artifact is None:
            self.session.add(
                IngestionArtifact(
                    ingestion_run_id=run.id,
                    raw_artifact_id=raw_row.id,
                )
            )

        events = adapter.parse(artifact)
        inserted = 0
        for event in events:
            revision = self._insert_event_revision(event, raw_row)
            if revision is not None:
                inserted += 1
                self._link_or_create_canonical(revision)
        self.session.commit()
        return IngestionResult(
            run_id=run.id,
            records_seen=len(events),
            revisions_inserted=inserted,
            artifacts_inserted=artifacts_inserted,
        )

    def _insert_event_revision(
        self, event: NormalizedEvent, raw_artifact: RawArtifact
    ) -> EventRevision | None:
        source_event = self.session.scalar(
            select(SourceEvent).where(
                SourceEvent.source_id == event.source_id,
                SourceEvent.source_event_id == event.source_event_id,
            )
        )
        if source_event is None:
            source_event = SourceEvent(
                source_id=event.source_id, source_event_id=event.source_event_id
            )
            self.session.add(source_event)
            self.session.flush()

        existing = self.session.scalar(
            select(EventRevision).where(
                EventRevision.source_event_id == source_event.id,
                EventRevision.revision_hash == event.revision_hash,
            )
        )
        if existing is not None:
            return None

        revision = EventRevision(
            source_event_id=source_event.id,
            raw_artifact_id=raw_artifact.id,
            revision_hash=event.revision_hash,
            event_time=event.event_time,
            source_updated_at=event.source_updated_at,
            received_at=event.received_at,
            available_at=event.available_at,
            latitude=event.latitude,
            longitude=event.longitude,
            depth_km=event.depth_km,
            magnitude=event.magnitude,
            magnitude_type=event.magnitude_type,
            place=event.place,
            status=event.status,
            location_uncertainty_km=event.location_uncertainty_km,
            depth_uncertainty_km=event.depth_uncertainty_km,
            magnitude_uncertainty=event.magnitude_uncertainty,
            geometry=WKTElement(f"POINT({event.longitude} {event.latitude})", srid=4326),
            parsed_payload=event.source_payload,
            parser_version=event.parser_version,
        )
        self.session.add(revision)
        self.session.flush()
        for issue in evaluate_event_quality(event):
            self.session.add(
                DataQualityLog(
                    event_revision_id=revision.id,
                    flag=issue.flag,
                    severity=issue.severity,
                    detail=issue.detail,
                )
            )
        return revision

    def _link_or_create_canonical(self, revision: EventRevision) -> None:
        current_membership = self.session.scalar(
            select(CanonicalEventMembership).where(
                CanonicalEventMembership.source_event_id == revision.source_event_id,
                CanonicalEventMembership.valid_until.is_(None),
            )
        )
        if current_membership is not None:
            return
        current_source_id = self.session.scalar(
            select(SourceEvent.source_id).where(SourceEvent.id == revision.source_event_id)
        )
        best_membership: CanonicalEventMembership | None = None
        best_probability = -1.0
        left = EventFingerprint(
            event_time=revision.event_time,
            latitude=revision.latitude,
            longitude=revision.longitude,
            depth_km=revision.depth_km,
            magnitude=revision.magnitude,
        )
        candidate_revisions = self._latest_other_revisions(revision)
        for other in candidate_revisions:
            result = self.scorer.compare(
                left,
                EventFingerprint(
                    event_time=other.event_time,
                    latitude=other.latitude,
                    longitude=other.longitude,
                    depth_km=other.depth_km,
                    magnitude=other.magnitude,
                ),
            )
            candidate_decision = result.decision
            if result.decision == "auto_match" and result.probability > best_probability:
                membership = self.session.scalar(
                    select(CanonicalEventMembership).where(
                        CanonicalEventMembership.source_event_id == other.source_event_id,
                        CanonicalEventMembership.valid_until.is_(None),
                    )
                )
                if membership is not None:
                    source_already_represented = self.session.scalar(
                        select(CanonicalEventMembership.id)
                        .join(
                            SourceEvent,
                            SourceEvent.id == CanonicalEventMembership.source_event_id,
                        )
                        .where(
                            CanonicalEventMembership.canonical_event_id
                            == membership.canonical_event_id,
                            CanonicalEventMembership.valid_until.is_(None),
                            SourceEvent.source_id == current_source_id,
                        )
                    )
                    if source_already_represented is None:
                        best_membership = membership
                        best_probability = result.probability
                    else:
                        candidate_decision = "canonical_source_conflict"
            self.session.add(
                DeduplicationCandidate(
                    left_event_revision_id=revision.id,
                    right_event_revision_id=other.id,
                    method_version=self.scorer.version,
                    match_probability=result.probability,
                    time_delta_seconds=result.time_delta_seconds,
                    distance_km=result.distance_km,
                    magnitude_delta=result.magnitude_delta,
                    depth_delta_km=result.depth_delta_km,
                    decision=candidate_decision,
                )
            )

        valid_from = revision.available_at
        if best_membership is not None:
            canonical_id = best_membership.canonical_event_id
            decision = "auto_match"
            probability = best_probability
        else:
            canonical = CanonicalEvent()
            self.session.add(canonical)
            self.session.flush()
            canonical_id = canonical.id
            decision = "singleton"
            probability = 1.0
        self.session.add(
            CanonicalEventMembership(
                canonical_event_id=canonical_id,
                source_event_id=revision.source_event_id,
                valid_from=valid_from,
                method_version=self.scorer.version,
                match_probability=probability,
                decision=decision,
            )
        )

    def _latest_other_revisions(self, revision: EventRevision) -> list[EventRevision]:
        window_start = revision.event_time - timedelta(minutes=5)
        window_end = revision.event_time + timedelta(minutes=5)
        current_source_id = self.session.scalar(
            select(SourceEvent.source_id).where(SourceEvent.id == revision.source_event_id)
        )
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
                .label("rank"),
            )
            .join(SourceEvent, SourceEvent.id == EventRevision.source_event_id)
            .where(
                and_(
                    EventRevision.source_event_id != revision.source_event_id,
                    SourceEvent.source_id != current_source_id,
                    EventRevision.event_time >= window_start,
                    EventRevision.event_time <= window_end,
                    EventRevision.available_at <= revision.available_at,
                )
            )
            .subquery()
        )
        return list(
            self.session.scalars(
                select(EventRevision)
                .join(ranked, ranked.c.revision_id == EventRevision.id)
                .where(ranked.c.rank == 1)
            )
        )

    @staticmethod
    def _suffix_for(media_type: str | None) -> str:
        media = (media_type or "").lower()
        if "json" in media:
            return ".json"
        if "html" in media:
            return ".html"
        if "csv" in media:
            return ".csv"
        if "xml" in media:
            return ".xml"
        return ".bin"


def archive_from_path(path: str | Path) -> RawArchive:
    return RawArchive(Path(path))
