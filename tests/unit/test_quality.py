from datetime import UTC, datetime

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.quality.validators import evaluate_event_quality


def test_missing_and_unknown_fields_are_flagged_without_dropping_event() -> None:
    event = NormalizedEvent(
        source_id="test",
        source_event_id="1",
        event_time=datetime(2026, 1, 1, tzinfo=UTC),
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        available_at=datetime(2026, 1, 1, tzinfo=UTC),
        latitude=-33,
        longitude=-72,
        source_payload={},
        parser_version="test",
    )
    flags = {issue.flag for issue in evaluate_event_quality(event)}
    assert {"missing_depth", "missing_magnitude", "unknown_magnitude_type"} <= flags
