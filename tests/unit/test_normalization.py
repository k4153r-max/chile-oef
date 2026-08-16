from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from chile_oef.catalog.normalization import NormalizedEvent


def make_event(**overrides: object) -> NormalizedEvent:
    values = {
        "source_id": "test",
        "source_event_id": "event-1",
        "event_time": datetime(2026, 1, 1, tzinfo=UTC),
        "received_at": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        "available_at": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        "latitude": -33.0,
        "longitude": -72.0,
        "depth_km": 20.0,
        "magnitude": 4.1,
        "magnitude_type": " Mw ",
        "source_payload": {"id": "event-1"},
        "parser_version": "test-v1",
    }
    values.update(overrides)
    return NormalizedEvent.model_validate(values)


def test_revision_hash_ignores_receipt_time_but_detects_scientific_change() -> None:
    first = make_event()
    later_receipt = make_event(
        received_at=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        available_at=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
    )
    revised = make_event(magnitude=4.2)

    assert first.magnitude_type == "mw"
    assert first.revision_hash == later_receipt.revision_hash
    assert first.revision_hash != revised.revision_hash


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        make_event(event_time=datetime(2026, 1, 1))


def test_available_at_cannot_precede_receipt() -> None:
    with pytest.raises(ValidationError, match="cannot precede"):
        make_event(available_at=datetime(2025, 12, 31, tzinfo=UTC))
