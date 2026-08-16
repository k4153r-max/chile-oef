import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from chile_oef.db.models import (
    CanonicalEventMembership,
    DataQualityLog,
    EventRevision,
    SourceEvent,
)


@dataclass(frozen=True)
class EventProjection:
    canonical_id: uuid.UUID
    revision_id: uuid.UUID
    source_id: str
    source_event_identifier: str
    event_time: datetime
    received_at: datetime
    available_at: datetime
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None
    magnitude_type: str | None
    place: str | None
    status: str | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must include a timezone")
    return value.astimezone(UTC)


def _preferred_projection_query(as_of: datetime):
    revision_ranked = (
        select(
            EventRevision.id.label("revision_id"),
            EventRevision.source_event_id.label("source_event_id"),
            func.row_number()
            .over(
                partition_by=EventRevision.source_event_id,
                order_by=(EventRevision.available_at.desc(), EventRevision.recorded_at.desc()),
            )
            .label("revision_rank"),
        )
        .where(EventRevision.available_at <= as_of)
        .subquery()
    )
    latest_revision = aliased(EventRevision)
    source_priority = case(
        (SourceEvent.source_id == "csn_daily", 0),
        (SourceEvent.source_id == "csn_compiled_catalog", 1),
        (SourceEvent.source_id == "usgs_comcat", 2),
        else_=100,
    )
    canonical_ranked = (
        select(
            CanonicalEventMembership.canonical_event_id.label("canonical_id"),
            latest_revision.id.label("revision_id"),
            SourceEvent.source_id.label("source_id"),
            SourceEvent.source_event_id.label("source_event_identifier"),
            latest_revision.event_time.label("event_time"),
            latest_revision.received_at.label("received_at"),
            latest_revision.available_at.label("available_at"),
            latest_revision.latitude.label("latitude"),
            latest_revision.longitude.label("longitude"),
            latest_revision.depth_km.label("depth_km"),
            latest_revision.magnitude.label("magnitude"),
            latest_revision.magnitude_type.label("magnitude_type"),
            latest_revision.place.label("place"),
            latest_revision.status.label("status"),
            func.row_number()
            .over(
                partition_by=CanonicalEventMembership.canonical_event_id,
                order_by=(source_priority, latest_revision.available_at.desc()),
            )
            .label("canonical_rank"),
        )
        .join(
            revision_ranked,
            and_(
                revision_ranked.c.source_event_id == SourceEvent.id,
                revision_ranked.c.revision_rank == 1,
            ),
        )
        .join(latest_revision, latest_revision.id == revision_ranked.c.revision_id)
        .join(
            CanonicalEventMembership,
            and_(
                CanonicalEventMembership.source_event_id == SourceEvent.id,
                CanonicalEventMembership.valid_from <= as_of,
                or_(
                    CanonicalEventMembership.valid_until.is_(None),
                    CanonicalEventMembership.valid_until > as_of,
                ),
            ),
        )
        .subquery()
    )
    return canonical_ranked


def list_events(
    session: Session,
    *,
    as_of: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    min_magnitude: float | None = None,
    min_latitude: float | None = None,
    max_latitude: float | None = None,
    min_longitude: float | None = None,
    max_longitude: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[EventProjection]:
    as_of = _as_utc(as_of or datetime.now(UTC))
    ranked = _preferred_projection_query(as_of)
    statement = select(ranked).where(ranked.c.canonical_rank == 1)
    if start_time is not None:
        statement = statement.where(ranked.c.event_time >= start_time)
    if end_time is not None:
        statement = statement.where(ranked.c.event_time < end_time)
    if min_magnitude is not None:
        statement = statement.where(ranked.c.magnitude >= min_magnitude)
    if min_latitude is not None:
        statement = statement.where(ranked.c.latitude >= min_latitude)
    if max_latitude is not None:
        statement = statement.where(ranked.c.latitude <= max_latitude)
    if min_longitude is not None:
        statement = statement.where(ranked.c.longitude >= min_longitude)
    if max_longitude is not None:
        statement = statement.where(ranked.c.longitude <= max_longitude)
    rows = session.execute(
        statement.order_by(ranked.c.event_time.desc()).limit(limit).offset(offset)
    ).mappings()
    return [
        EventProjection(**{key: row[key] for key in EventProjection.__annotations__})
        for row in rows
    ]


def get_event_revisions(
    session: Session, canonical_id: uuid.UUID, *, as_of: datetime | None = None
) -> list[tuple[EventRevision, SourceEvent, list[DataQualityLog]]]:
    as_of = _as_utc(as_of or datetime.now(UTC))
    statement = (
        select(EventRevision, SourceEvent)
        .join(SourceEvent, SourceEvent.id == EventRevision.source_event_id)
        .join(
            CanonicalEventMembership,
            CanonicalEventMembership.source_event_id == SourceEvent.id,
        )
        .where(
            CanonicalEventMembership.canonical_event_id == canonical_id,
            CanonicalEventMembership.valid_from <= as_of,
            or_(
                CanonicalEventMembership.valid_until.is_(None),
                CanonicalEventMembership.valid_until > as_of,
            ),
            EventRevision.available_at <= as_of,
        )
        .order_by(SourceEvent.source_id, EventRevision.available_at.desc())
    )
    output: list[tuple[EventRevision, SourceEvent, list[DataQualityLog]]] = []
    for revision, source_event in session.execute(statement):
        quality = list(
            session.scalars(
                select(DataQualityLog).where(DataQualityLog.event_revision_id == revision.id)
            )
        )
        output.append((revision, source_event, quality))
    return output
