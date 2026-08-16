import json
from datetime import UTC, datetime
from pathlib import Path

from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.sources.usgs_geojson import UsgsGeoJsonAdapter


def test_usgs_geojson_parser_preserves_source_identity_and_uncertainty() -> None:
    content = Path("tests/fixtures/usgs/all_hour.geojson").read_bytes()
    received_at = datetime(2026, 8, 16, tzinfo=UTC)
    artifact = FetchedArtifact(
        source_id="usgs_comcat",
        source_url="https://example.test/all_hour.geojson",
        retrieved_at=received_at,
        content=content,
        media_type="application/geo+json",
    )

    events = UsgsGeoJsonAdapter().parse(artifact)

    assert len(events) == 2
    first = events[0]
    assert first.source_event_id == "us-test-001"
    assert first.longitude == -72.4
    assert first.latitude == -33.1
    assert first.depth_km == 25.0
    assert first.magnitude == 4.2
    assert first.magnitude_type == "mww"
    assert first.location_uncertainty_km == 5.1
    assert first.received_at == received_at
    assert first.available_at == received_at


def test_usgs_global_feed_is_filtered_to_chile_study_bounds() -> None:
    document = json.loads(Path("tests/fixtures/usgs/all_hour.geojson").read_bytes())
    outside = dict(document["features"][0])
    outside["id"] = "us-outside-study-region"
    outside["geometry"] = {"type": "Point", "coordinates": [-118.2, 34.1, 8.0]}
    document["features"].append(outside)
    artifact = FetchedArtifact(
        source_id="usgs_comcat",
        source_url="https://example.test/all_hour.geojson",
        retrieved_at=datetime(2026, 8, 16, tzinfo=UTC),
        content=json.dumps(document).encode(),
        media_type="application/geo+json",
    )

    events = UsgsGeoJsonAdapter().parse(artifact)

    assert {event.source_event_id for event in events} == {"us-test-001", "us-test-002"}
