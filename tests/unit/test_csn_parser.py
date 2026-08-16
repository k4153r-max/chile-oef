from datetime import UTC, datetime
from pathlib import Path

from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.sources.csn_daily import CsnDailyAdapter


def test_csn_daily_parser_uses_utc_column_and_report_identifier() -> None:
    content = Path("tests/fixtures/csn/20260721.html").read_bytes()
    retrieved_at = datetime(2026, 7, 22, tzinfo=UTC)
    adapter = CsnDailyAdapter(datetime(2026, 7, 21).date())
    artifact = FetchedArtifact(
        source_id="csn_daily",
        source_url=adapter.url,
        retrieved_at=retrieved_at,
        content=content,
        media_type="text/html",
    )

    events = adapter.parse(artifact)

    assert len(events) == 2
    first = events[0]
    assert first.source_event_id == "375778"
    assert first.event_time == datetime(2026, 7, 21, 17, 21, 7, tzinfo=UTC)
    assert first.latitude == -57.190
    assert first.longitude == -67.000
    assert first.depth_km == 10
    assert first.magnitude == 4.7
    assert first.magnitude_type == "mw"
    assert first.place == "254 km al S de Puerto Williams"
