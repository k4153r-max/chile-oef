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


def test_csn_daily_parser_handles_a_busy_day_with_multiple_magnitude_types() -> None:
    """2026-07-18 mixes mlv (local) and mww (moment, teleseismic) in one page."""
    content = Path("tests/fixtures/csn/20260718.html").read_bytes()
    adapter = CsnDailyAdapter(datetime(2026, 7, 18).date())
    artifact = FetchedArtifact(
        source_id="csn_daily",
        source_url=adapter.url,
        retrieved_at=datetime(2026, 7, 19, tzinfo=UTC),
        content=content,
        media_type="text/html",
    )

    events = adapter.parse(artifact)

    assert len(events) == 34
    assert {e.magnitude_type for e in events} == {"mlv", "mww"}

    teleseismic = next(e for e in events if e.magnitude_type == "mww")
    assert teleseismic.source_event_id == "375377"
    assert teleseismic.magnitude == 5.7
    assert teleseismic.place == "443 km al E de Base Frei"


def test_csn_daily_parser_handles_a_quiet_local_magnitude_only_day() -> None:
    content = Path("tests/fixtures/csn/20260811.html").read_bytes()
    adapter = CsnDailyAdapter(datetime(2026, 8, 11).date())
    artifact = FetchedArtifact(
        source_id="csn_daily",
        source_url=adapter.url,
        retrieved_at=datetime(2026, 8, 12, tzinfo=UTC),
        content=content,
        media_type="text/html",
    )

    events = adapter.parse(artifact)

    assert len(events) == 17
    assert {e.magnitude_type for e in events} == {"mlv"}
    first = events[0]
    assert first.source_event_id == "378880"
    assert first.latitude == -21.263
    assert first.longitude == -68.601
    assert first.depth_km == 124.0


def test_csn_daily_parser_captures_events_below_usgs_practical_threshold() -> None:
    """2026-08-18: all 22 events are M<=3.9, well under the ~M5 USGS
    completeness cutoff CHILE-OEF currently uses -- this is the whole point
    of enabling CSN as a source. Cross-checked against a live CSN summary
    fetched the same day (Rancagua M3.8, Quintero M2.6, Puerto Montt M2.7)."""
    content = Path("tests/fixtures/csn/20260818.html").read_bytes()
    adapter = CsnDailyAdapter(datetime(2026, 8, 18).date())
    artifact = FetchedArtifact(
        source_id="csn_daily",
        source_url=adapter.url,
        retrieved_at=datetime(2026, 8, 18, 15, tzinfo=UTC),
        content=content,
        media_type="text/html",
    )

    events = adapter.parse(artifact)

    assert len(events) == 22
    assert max(e.magnitude for e in events) < 5.0

    rancagua = next(e for e in events if e.source_event_id == "379738")
    assert rancagua.magnitude == 3.8
    assert rancagua.place == "38 km al N de Rancagua"
    assert rancagua.event_time == datetime(2026, 8, 18, 11, 50, 17, tzinfo=UTC)

    puerto_montt = next(e for e in events if e.source_event_id == "379714")
    assert puerto_montt.magnitude == 2.7
    assert puerto_montt.place == "28 km al N de Puerto Montt"

    quintero = next(e for e in events if e.source_event_id == "379707")
    assert quintero.magnitude == 2.6
    assert quintero.place == "28 km al NO de Quintero"


def test_csn_daily_parser_handles_a_different_season() -> None:
    """2026-05-01: same schema, different month -- guards against
    seasonal/rendering quirks that a single fixture day could hide."""
    content = Path("tests/fixtures/csn/20260501.html").read_bytes()
    adapter = CsnDailyAdapter(datetime(2026, 5, 1).date())
    artifact = FetchedArtifact(
        source_id="csn_daily",
        source_url=adapter.url,
        retrieved_at=datetime(2026, 5, 2, tzinfo=UTC),
        content=content,
        media_type="text/html",
    )

    events = adapter.parse(artifact)

    assert len(events) == 24
    assert {e.magnitude_type for e in events} == {"mlv"}
