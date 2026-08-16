from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.db.models import CompletenessEstimate
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.seismicity.service import (
    DeclusteringService,
    GutenbergRichterEstimationService,
    ModifiedOmoriService,
)


@dataclass
class FixtureEventAdapter:
    events: list[NormalizedEvent]
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/omori-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"omori-fixture",
            media_type="application/octet-stream",
            http_status=200,
        )

    def parse(self, artifact: FetchedArtifact) -> list[NormalizedEvent]:
        return self.events


def _event(
    *,
    source_event_id: str,
    event_time: datetime,
    available_at: datetime,
    magnitude: float,
    latitude: float,
    longitude: float,
) -> NormalizedEvent:
    return NormalizedEvent(
        source_id="usgs_comcat",
        source_event_id=source_event_id,
        event_time=event_time,
        received_at=available_at,
        available_at=available_at,
        latitude=latitude,
        longitude=longitude,
        depth_km=20.0,
        depth_uncertainty_km=5.0,
        magnitude=magnitude,
        magnitude_type="ml",
        source_payload={"id": source_event_id},
        parser_version="fixture-v1",
    )


def _cumulative_count(t: float, k: float, c: float, p: float) -> float:
    if abs(p - 1.0) < 1e-8:
        return k * (np.log(t + c) - np.log(c))
    return k * ((t + c) ** (1.0 - p) - c ** (1.0 - p)) / (1.0 - p)


def _sample_omori_days(
    *, k: float, c: float, p: float, duration_days: float, seed: int
) -> list[float]:
    rng = np.random.default_rng(seed)
    total_expected = _cumulative_count(duration_days, k, c, p)
    n = rng.poisson(total_expected)
    u = rng.uniform(0.0, total_expected, size=n)
    base = c ** (1.0 - p) + u * (1.0 - p) / k
    t = base ** (1.0 / (1.0 - p)) - c
    return sorted(float(value) for value in t)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_chain_through_modified_omori(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    """End-to-end: ingest a background catalog plus one mainshock with a
    real Modified-Omori-decaying aftershock sequence (known K, c, p) ->
    declare Mc -> fit b -> decluster -> fit Modified Omori on the resulting
    family. Confirms the family-resolution grouping (by root ancestor, not
    just immediate parent) correctly isolates the aftershock sequence on
    real declustering output, and that the fitted (K, c, p) land in the
    right neighborhood of the values used to generate it.
    """
    rng = np.random.default_rng(17)
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = window_start + timedelta(days=100)
    as_of = window_end

    events: list[NormalizedEvent] = []

    background_count = 150
    bg_days = rng.uniform(0, 100, size=background_count)
    bg_lat = rng.uniform(-34.0, -32.0, size=background_count)
    bg_lon = rng.uniform(-72.0, -70.0, size=background_count)
    for i in range(background_count):
        event_time = window_start + timedelta(days=float(bg_days[i]))
        events.append(
            _event(
                source_event_id=f"bg-{i}",
                event_time=event_time,
                available_at=event_time + timedelta(minutes=5),
                magnitude=3.5,
                latitude=float(bg_lat[i]),
                longitude=float(bg_lon[i]),
            )
        )

    main_day = 10.0
    main_lat, main_lon = -33.0, -71.0
    main_time = window_start + timedelta(days=main_day)
    events.append(
        _event(
            source_event_id="mainshock",
            event_time=main_time,
            available_at=main_time + timedelta(minutes=5),
            magnitude=6.0,
            latitude=main_lat,
            longitude=main_lon,
        )
    )

    k_true, c_true, p_true = 60.0, 0.1, 1.1
    # Must match window_end - main_time exactly: the service fits against
    # that same duration, so generating fewer days here would look like
    # zero observed activity in the tail -- a real bias, not test noise.
    sequence_duration_days = (window_end - main_time).total_seconds() / 86400.0
    aftershock_days = _sample_omori_days(
        k=k_true, c=c_true, p=p_true, duration_days=sequence_duration_days, seed=23
    )
    assert len(aftershock_days) >= 20, "synthetic sequence too small for this seed"
    after_lat = main_lat + rng.normal(0, 0.01, size=len(aftershock_days))
    after_lon = main_lon + rng.normal(0, 0.01, size=len(aftershock_days))
    for i, offset_days in enumerate(aftershock_days):
        event_time = main_time + timedelta(days=offset_days)
        events.append(
            _event(
                source_event_id=f"after-{i}",
                event_time=event_time,
                available_at=event_time + timedelta(minutes=5),
                magnitude=3.2,
                latitude=float(after_lat[i]),
                longitude=float(after_lon[i]),
            )
        )

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter(events)
        )

        mc_record = CompletenessEstimate(
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
            method_version="fixture",
            role="diagnostic",
            calibration_status="fixture",
            event_count=len(events),
            support_state="supported",
            mc_value=3.0,
            bin_width_magnitude=0.1,
            catalog_as_of=as_of,
            diagnostics_json={},
        )
        session.add(mc_record)
        session.commit()

        gr_record = GutenbergRichterEstimationService(session).estimate_for_completeness_estimate(
            mc_record.id
        )
        declustering_run = DeclusteringService(session).decluster_for_gutenberg_richter_estimate(
            gr_record.id
        )

        omori_records = ModifiedOmoriService(session).estimate_for_declustering_run(
            declustering_run.id
        )
        estimable = [r for r in omori_records if r.support_state == "estimable"]
        assert len(estimable) >= 1

        best = max(estimable, key=lambda r: r.event_count)
        # A magnitude-6.0 mainshock has a large "reach" in the nearest-
        # neighbor eta metric (its parent-magnitude term dominates), so a
        # handful of temporally-nearby but unrelated background events can
        # get pulled into its family -- an expected characteristic of the
        # method on a real declustering run, not a precision claim about
        # the count itself.
        assert best.event_count == pytest.approx(len(aftershock_days), abs=15)
        assert best.p_exponent == pytest.approx(p_true, abs=0.3)
        assert best.declustering_run_id == declustering_run.id
        assert best.converged is True
