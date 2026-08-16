import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from chile_oef.db.repositories.events import list_events


@dataclass(frozen=True)
class MagnitudeObservation:
    event_time: datetime
    magnitude: float
    magnitude_type: str


@dataclass(frozen=True)
class CatalogSelection:
    observations: tuple[MagnitudeObservation, ...]
    catalog_as_of: datetime
    start_time: datetime
    end_time: datetime
    magnitude_type: str
    min_latitude: float | None
    max_latitude: float | None
    min_longitude: float | None
    max_longitude: float | None

    @property
    def event_count(self) -> int:
        return len(self.observations)


def select_single_magnitude_type(
    observations: Sequence[MagnitudeObservation], magnitude_type: str
) -> list[MagnitudeObservation]:
    """Keep only observations reported natively in one magnitude type.

    completeness.md requires Mc to be estimated per magnitude type: mixing
    scales without a registered conversion (see config/magnitude-policy.yaml)
    would silently bias the frequency-magnitude distribution.
    """
    return [
        observation for observation in observations if observation.magnitude_type == magnitude_type
    ]


def fetch_magnitude_catalog(
    session: Session,
    *,
    as_of: datetime,
    start_time: datetime,
    end_time: datetime,
    magnitude_type: str,
    min_latitude: float | None = None,
    max_latitude: float | None = None,
    min_longitude: float | None = None,
    max_longitude: float | None = None,
    limit: int = 200_000,
) -> CatalogSelection:
    """Select an availability-safe magnitude sample for completeness estimation.

    Reuses ``list_events``, whose preferred-revision query already enforces
    ``available_at <= as_of`` and the canonical-event priority order, so this
    function only adds the single-magnitude-type restriction Mc requires.
    """
    if start_time.tzinfo is None or end_time.tzinfo is None or as_of.tzinfo is None:
        raise ValueError("start_time, end_time and as_of must be timezone-aware")
    if start_time >= end_time:
        raise ValueError("start_time must be before end_time")

    projections = list_events(
        session,
        as_of=as_of,
        start_time=start_time,
        end_time=end_time,
        min_latitude=min_latitude,
        max_latitude=max_latitude,
        min_longitude=min_longitude,
        max_longitude=max_longitude,
        limit=limit,
    )
    observations = [
        MagnitudeObservation(
            event_time=projection.event_time,
            magnitude=projection.magnitude,
            magnitude_type=projection.magnitude_type,
        )
        for projection in projections
        if projection.magnitude is not None and projection.magnitude_type is not None
    ]
    observations = select_single_magnitude_type(observations, magnitude_type)
    return CatalogSelection(
        observations=tuple(observations),
        catalog_as_of=as_of,
        start_time=start_time,
        end_time=end_time,
        magnitude_type=magnitude_type,
        min_latitude=min_latitude,
        max_latitude=max_latitude,
        min_longitude=min_longitude,
        max_longitude=max_longitude,
    )


@dataclass(frozen=True)
class SpatialEventObservation:
    # References EventRevision.id (not the canonical/deduplicated event id),
    # matching the convention EventTectonicClassification already uses for
    # per-event persistence.
    event_revision_id: uuid.UUID
    event_time: datetime
    latitude: float
    longitude: float
    magnitude: float
    magnitude_type: str


def fetch_declustering_catalog(
    session: Session,
    *,
    as_of: datetime,
    start_time: datetime,
    end_time: datetime,
    magnitude_type: str,
    minimum_magnitude: float,
    min_latitude: float | None = None,
    max_latitude: float | None = None,
    min_longitude: float | None = None,
    max_longitude: float | None = None,
    limit: int = 200_000,
) -> tuple[SpatialEventObservation, ...]:
    """Select an availability-safe, located sample for declustering.

    Declustering needs coordinates (not just magnitude), a single magnitude
    type for the same reason Mc/Gutenberg-Richter do, and a minimum
    magnitude -- below the declared Mc the catalog is not complete enough
    for the nearest-neighbor space-time-magnitude metric to be meaningful.
    """
    if start_time.tzinfo is None or end_time.tzinfo is None or as_of.tzinfo is None:
        raise ValueError("start_time, end_time and as_of must be timezone-aware")
    if start_time >= end_time:
        raise ValueError("start_time must be before end_time")

    projections = list_events(
        session,
        as_of=as_of,
        start_time=start_time,
        end_time=end_time,
        min_magnitude=minimum_magnitude,
        min_latitude=min_latitude,
        max_latitude=max_latitude,
        min_longitude=min_longitude,
        max_longitude=max_longitude,
        limit=limit,
    )
    return tuple(
        SpatialEventObservation(
            event_revision_id=projection.revision_id,
            event_time=projection.event_time,
            latitude=projection.latitude,
            longitude=projection.longitude,
            magnitude=projection.magnitude,
            magnitude_type=projection.magnitude_type,
        )
        for projection in projections
        if projection.magnitude is not None
        and projection.magnitude_type == magnitude_type
        and projection.latitude is not None
        and projection.longitude is not None
    )
