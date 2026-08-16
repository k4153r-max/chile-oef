from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import norm
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.seismicity.catalog_selection import fetch_magnitude_catalog
from chile_oef.seismicity.completeness import CompletenessPolicy
from chile_oef.seismicity.service import (
    CompletenessEstimationService,
    GutenbergRichterEstimationService,
)


@dataclass
class FixtureEventAdapter:
    events: list[NormalizedEvent]
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/completeness-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"completeness-fixture",
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
    magnitude_type: str = "ml",
) -> NormalizedEvent:
    return NormalizedEvent(
        source_id="usgs_comcat",
        source_event_id=source_event_id,
        event_time=event_time,
        received_at=available_at,
        available_at=available_at,
        latitude=-33.0,
        longitude=-71.5,
        depth_km=20.0,
        depth_uncertainty_km=5.0,
        magnitude=magnitude,
        magnitude_type=magnitude_type,
        source_payload={"id": source_event_id},
        parser_version="fixture-v1",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_availability_invariant_excludes_late_arriving_revision(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = datetime(2026, 2, 1, tzinfo=UTC)
    as_of = datetime(2026, 1, 20, tzinfo=UTC)

    on_time = _event(
        source_event_id="ontime-1",
        event_time=window_start + timedelta(days=5),
        available_at=window_start + timedelta(days=5, hours=1),
        magnitude=3.4,
    )
    # available_at is after as_of: the availability invariant in
    # docs/forecast-contract.md must exclude this revision even though its
    # event_time falls inside the window.
    late_arriving = _event(
        source_event_id="late-1",
        event_time=window_start + timedelta(days=6),
        available_at=as_of + timedelta(days=1),
        magnitude=5.9,
    )
    wrong_scale = _event(
        source_event_id="wrong-scale-1",
        event_time=window_start + timedelta(days=7),
        available_at=window_start + timedelta(days=7, hours=1),
        magnitude=4.1,
        magnitude_type="mw",
    )

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter([on_time, late_arriving, wrong_scale])
        )

        selection = fetch_magnitude_catalog(
            session,
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert [o.magnitude for o in selection.observations] == [3.4]

        record = CompletenessEstimationService(
            session, policy=CompletenessPolicy()
        ).estimate_maximum_curvature(
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert record.event_count == 1
        assert record.support_state == "not_estimable"
        assert record.mc_value is None
        assert record.role == "diagnostic"
        assert record.catalog_as_of == as_of


@pytest.mark.integration
@pytest.mark.asyncio
async def test_estimate_persists_supported_band_result(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = datetime(2026, 2, 1, tzinfo=UTC)
    as_of = window_end

    events = [
        _event(
            source_event_id=f"bulk-{index}",
            event_time=window_start + timedelta(hours=index),
            available_at=window_start + timedelta(hours=index, minutes=5),
            magnitude=3.0,
        )
        for index in range(200)
    ]
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter(events)
        )

        record = CompletenessEstimationService(session).estimate_maximum_curvature(
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert record.event_count == 200
        assert record.support_state == "supported"
        assert record.mc_value == pytest.approx(3.2)
        assert record.id is not None


def _exact_gr_magnitudes(
    *, mc_true: float, b_value: float, n0: int, bin_width: float
) -> list[float]:
    top_magnitude = mc_true + 2.0
    bin_count = round((top_magnitude - mc_true) / bin_width) + 1
    bins = [round(mc_true + index * bin_width, 10) for index in range(bin_count)]
    cumulative = {
        bin_value: round(n0 * 10 ** (-b_value * (bin_value - mc_true))) for bin_value in bins
    }
    noncumulative = {
        bin_value: (
            cumulative[bin_value] - cumulative[bins[index + 1]]
            if index + 1 < len(bins)
            else cumulative[bin_value]
        )
        for index, bin_value in enumerate(bins)
    }
    for bin_value in (round(mc_true - index * bin_width, 10) for index in range(1, 11)):
        noncumulative[bin_value] = 3
    magnitudes: list[float] = []
    for bin_value, count in noncumulative.items():
        magnitudes.extend([bin_value] * count)
    return magnitudes


@pytest.mark.integration
@pytest.mark.asyncio
async def test_goodness_of_fit_estimate_persists_through_the_service(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    as_of = window_start + timedelta(days=400)
    window_end = as_of

    magnitudes = _exact_gr_magnitudes(mc_true=3.0, b_value=1.0, n0=200, bin_width=0.1)
    events = [
        _event(
            source_event_id=f"gof-{index}",
            event_time=window_start + timedelta(hours=index),
            available_at=window_start + timedelta(hours=index, minutes=5),
            magnitude=magnitude,
        )
        for index, magnitude in enumerate(magnitudes)
    ]
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter(events)
        )

        record = CompletenessEstimationService(session).estimate_goodness_of_fit(
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert record.event_count == len(magnitudes)
        assert record.mc_value == pytest.approx(3.0)
        assert record.diagnostics_json["achieved_confidence_percent"] == pytest.approx(95.0)
        assert record.method_version == "goodness_of_fit_diagnostic_v1"
        assert record.id is not None


def _normal_rolloff_magnitudes(*, seed: int, sample_size: int, true_mu: float) -> list[float]:
    rng = np.random.default_rng(seed)
    true_sigma, true_b = 0.12, 1.0
    beta = true_b * np.log(10.0)
    floor, cap = true_mu - 1.5, true_mu + 3.0

    def gr_density(magnitude: np.ndarray) -> np.ndarray:
        return beta * np.exp(-beta * (magnitude - floor))

    def detection_probability(magnitude: np.ndarray) -> np.ndarray:
        return norm.cdf((magnitude - true_mu) / true_sigma)

    envelope = gr_density(np.array([floor]))[0]
    accepted: list[float] = []
    while len(accepted) < sample_size:
        batch = rng.uniform(floor, cap, size=4000)
        acceptance = gr_density(batch) * detection_probability(batch) / envelope
        draws = rng.uniform(0.0, 1.0, size=4000)
        accepted.extend(batch[draws < acceptance].tolist())
    return accepted[:sample_size]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_entire_magnitude_range_estimate_persists_through_the_service(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    as_of = window_start + timedelta(days=400)
    window_end = as_of
    true_mu = 3.0

    magnitudes = _normal_rolloff_magnitudes(seed=11, sample_size=500, true_mu=true_mu)
    events = [
        _event(
            source_event_id=f"emr-{index}",
            event_time=window_start + timedelta(hours=index),
            available_at=window_start + timedelta(hours=index, minutes=5),
            magnitude=magnitude,
        )
        for index, magnitude in enumerate(magnitudes)
    ]
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter(events)
        )

        record = CompletenessEstimationService(
            session, policy=CompletenessPolicy(emr_bootstrap_resamples=15)
        ).estimate_entire_magnitude_range(
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert record.event_count == len(magnitudes)
        assert record.role == "primary"
        assert record.calibration_status == "uncalibrated_primary_estimator"
        assert record.diagnostics_json["converged"] is True
        assert record.mc_value == pytest.approx(true_mu, abs=0.2)
        assert record.diagnostics_json["bootstrap_resamples_converged"] > 0
        assert record.id is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gutenberg_richter_chains_onto_a_specific_completeness_estimate(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    """End-to-end: ingest -> fit Mc with Entire Magnitude Range -> fit b
    above that specific Mc row's threshold, and confirm the b-value estimate
    records the exact completeness_estimate_id it depended on.
    """
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    as_of = window_start + timedelta(days=400)
    window_end = as_of
    true_mu = 3.0

    magnitudes = _normal_rolloff_magnitudes(seed=11, sample_size=500, true_mu=true_mu)
    events = [
        _event(
            source_event_id=f"gr-chain-{index}",
            event_time=window_start + timedelta(hours=index),
            available_at=window_start + timedelta(hours=index, minutes=5),
            magnitude=magnitude,
        )
        for index, magnitude in enumerate(magnitudes)
    ]
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter(events)
        )

        completeness_service = CompletenessEstimationService(
            session, policy=CompletenessPolicy(emr_bootstrap_resamples=15)
        )
        mc_record = completeness_service.estimate_entire_magnitude_range(
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert mc_record.mc_value is not None

        gr_record = GutenbergRichterEstimationService(session).estimate_for_completeness_estimate(
            mc_record.id
        )

        assert gr_record.completeness_estimate_id == mc_record.id
        assert gr_record.mc_used == mc_record.mc_value
        assert gr_record.start_time == mc_record.start_time
        assert gr_record.end_time == mc_record.end_time
        assert gr_record.magnitude_type == mc_record.magnitude_type
        assert gr_record.support_state != "not_estimable"
        assert gr_record.b_value == pytest.approx(1.0, abs=0.2)
        assert gr_record.b_value_standard_error is not None
        assert gr_record.id is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gutenberg_richter_refuses_a_completeness_estimate_without_mc(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = window_start + timedelta(days=1)
    as_of = window_end

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        # No events ingested at all: the completeness estimate is
        # not_estimable and carries mc_value=None.
        mc_record = CompletenessEstimationService(session).estimate_maximum_curvature(
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert mc_record.mc_value is None

        with pytest.raises(ValueError, match="no mc_value"):
            GutenbergRichterEstimationService(session).estimate_for_completeness_estimate(
                mc_record.id
            )
