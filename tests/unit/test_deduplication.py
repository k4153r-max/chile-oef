from datetime import UTC, datetime, timedelta

import pytest

from chile_oef.catalog.deduplication import (
    DeduplicationScorer,
    EventFingerprint,
    haversine_km,
)


def event(**overrides: object) -> EventFingerprint:
    values = {
        "event_time": datetime(2026, 1, 1, tzinfo=UTC),
        "latitude": -33.0,
        "longitude": -72.0,
        "depth_km": 20.0,
        "magnitude": 5.0,
    }
    values.update(overrides)
    return EventFingerprint(**values)


def test_identical_observations_auto_match() -> None:
    result = DeduplicationScorer().compare(event(), event())
    assert result.probability == pytest.approx(1.0)
    assert result.decision == "auto_match"


def test_distant_events_are_distinct() -> None:
    right = event(
        event_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=1),
        latitude=-23.0,
    )
    result = DeduplicationScorer().compare(event(), right)
    assert result.decision == "distinct"
    assert result.probability < 0.01


def test_haversine_is_symmetric() -> None:
    forward = haversine_km(-33, -72, -34, -71)
    backward = haversine_km(-34, -71, -33, -72)
    assert forward == pytest.approx(backward)
    assert 140 < forward < 150
