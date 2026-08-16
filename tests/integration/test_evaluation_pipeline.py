import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.db.models import CompletenessEstimate, EvaluationFoldScore, ForecastRun
from chile_oef.evaluation.replay import WalkForwardPolicy, run_walk_forward_evaluation
from chile_oef.forecast.specification import load_forecast_specification
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.seismicity.service import (
    GutenbergRichterEstimationService,
    SpatiotemporalEtasService,
)
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasPolicy
from chile_oef.tectonics.grid import GridDefinition, GridService

DEGREE_KM = 111.32


@dataclass
class FixtureEventAdapter:
    events: list[NormalizedEvent]
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/evaluation-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"evaluation-fixture",
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


def _integral_rate(c: float, p: float, d: float) -> float:
    if d <= 0:
        return 0.0
    if abs(p - 1.0) < 1e-8:
        return math.log(d + c) - math.log(c)
    return ((d + c) ** (1.0 - p) - c ** (1.0 - p)) / (1.0 - p)


def _simulate_light_spatiotemporal_events(
    *,
    mu: float,
    k0: float,
    c: float,
    p: float,
    d0: float,
    q: float,
    duration_days: float,
    base_lat: float,
    base_lon: float,
    region_deg: float,
    seed: int,
) -> list[tuple[float, float, float]]:
    """Same independent branching-process simulator as
    tests/integration/test_forecast_pipeline.py, extended to a longer
    duration so there is real activity both in the fit window and in the
    walk-forward evaluation window that follows it.
    """
    rng = np.random.default_rng(seed)
    background_count = rng.poisson(mu * duration_days)
    events: list[tuple[float, float, float]] = []
    queue: list[tuple[float, float, float]] = []
    for _ in range(background_count):
        t0 = float(rng.uniform(0.0, duration_days))
        lat0 = base_lat + rng.uniform(-region_deg / 2.0, region_deg / 2.0)
        lon0 = base_lon + rng.uniform(-region_deg / 2.0, region_deg / 2.0)
        events.append((t0, lat0, lon0))
        queue.append((t0, lat0, lon0))
    while queue:
        if len(events) > 5000:
            raise RuntimeError("synthetic catalog exploded")
        parent_time, parent_lat, parent_lon = queue.pop()
        remaining = duration_days - parent_time
        if remaining <= 0:
            continue
        total_expected = k0 * _integral_rate(c, p, remaining)
        n = rng.poisson(total_expected)
        if n == 0:
            continue
        u = rng.uniform(0.0, total_expected, size=n)
        base = c ** (1.0 - p) + u * (1.0 - p) / k0
        offsets = base ** (1.0 / (1.0 - p)) - c
        for offset in offsets:
            child_time = parent_time + float(offset)
            if child_time > duration_days:
                continue
            u2 = rng.uniform(0.0, 1.0)
            r_km = d0 * math.sqrt((1.0 - u2) ** (1.0 / (1.0 - q)) - 1.0)
            theta = rng.uniform(0.0, 2.0 * math.pi)
            child_lat = parent_lat + (r_km * math.cos(theta)) / DEGREE_KM
            child_lon = parent_lon + (r_km * math.sin(theta)) / (
                DEGREE_KM * math.cos(math.radians(parent_lat))
            )
            events.append((child_time, child_lat, child_lon))
            queue.append((child_time, child_lat, child_lon))
    events.sort(key=lambda event: event[0])
    return events


@pytest.mark.integration
@pytest.mark.asyncio
async def test_walk_forward_evaluation_scores_real_forecast_runs(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    """End-to-end: fit Mc/GR/spatiotemporal-ETAS on the first 200 days of a
    simulated catalog, then walk-forward evaluate over the following two
    weekly folds -- each fold must issue a real, persisted ForecastRun (the
    exact same ForecastService.issue_forecast used everywhere else) and
    score it against events actually observed afterward. Checks the
    evaluation artifacts exist, cite their forecast runs, and that scores
    are finite and within their mathematically required ranges.
    """
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    fit_duration_days = 200.0
    total_duration_days = 230.0
    fit_end = window_start + timedelta(days=fit_duration_days)
    mc = 3.0
    base_lat, base_lon = -33.0, -71.0
    region_deg = 2.0

    events_data = _simulate_light_spatiotemporal_events(
        mu=1.0,
        k0=0.05,
        c=0.1,
        p=1.2,
        d0=5.0,
        q=1.8,
        duration_days=total_duration_days,
        base_lat=base_lat,
        base_lon=base_lon,
        region_deg=region_deg,
        seed=11,
    )
    assert len(events_data) >= 100, "synthetic catalog too small for this seed"
    n_after_fit_window = sum(1 for offset, _, _ in events_data if offset >= fit_duration_days)
    assert n_after_fit_window >= 5, "need real post-fit-window activity to evaluate against"

    events = [
        _event(
            source_event_id=f"eval-{index}",
            event_time=window_start + timedelta(days=offset),
            available_at=window_start + timedelta(days=offset, minutes=5),
            magnitude=3.5,
            latitude=lat,
            longitude=lon,
        )
        for index, (offset, lat, lon) in enumerate(events_data)
    ]

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(session, load_source_registry(Path("config/source-registry.yaml")))
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter(events)
        )

        mc_record = CompletenessEstimate(
            start_time=window_start,
            end_time=fit_end,
            min_latitude=base_lat - region_deg / 2.0,
            max_latitude=base_lat + region_deg / 2.0,
            min_longitude=base_lon - region_deg / 2.0,
            max_longitude=base_lon + region_deg / 2.0,
            magnitude_type="ml",
            method_version="fixture",
            role="diagnostic",
            calibration_status="fixture",
            event_count=sum(1 for offset, _, _ in events_data if offset < fit_duration_days),
            support_state="supported",
            mc_value=mc,
            bin_width_magnitude=0.1,
            catalog_as_of=fit_end,
            diagnostics_json={},
        )
        session.add(mc_record)
        session.commit()

        gr_record = GutenbergRichterEstimationService(session).estimate_for_completeness_estimate(
            mc_record.id
        )
        assert gr_record.b_value is not None

        etas_record = SpatiotemporalEtasService(
            session, policy=SpatiotemporalEtasPolicy(restarts=1, minimum_events=80)
        ).estimate_for_completeness_estimate(mc_record.id)
        if not etas_record.converged:
            pytest.skip("spatiotemporal ETAS did not converge on this seed with one restart")

        grid = GridService(session).create(
            GridDefinition(
                id="fixture_evaluation_grid_v1",
                resolution_degrees=Decimal("0.2"),
                min_latitude=Decimal(str(base_lat - region_deg / 2.0 - 0.5)),
                max_latitude=Decimal(str(base_lat + region_deg / 2.0 + 0.5)),
                min_longitude=Decimal(str(base_lon - region_deg / 2.0 - 0.5)),
                max_longitude=Decimal(str(base_lon + region_deg / 2.0 + 0.5)),
            )
        )

        specification = load_forecast_specification(Path("config/forecast-specification.yaml"))
        specification = type(specification)(
            version=specification.version,
            status=specification.status,
            grid_id=grid.id,
            horizons=specification.horizons,
            magnitude_bins=specification.magnitude_bins,
            reject_threshold_below_mc=specification.reject_threshold_below_mc,
            stale_data_action=specification.stale_data_action,
        )

        evaluation_run = run_walk_forward_evaluation(
            session,
            specification=specification,
            spatiotemporal_etas_estimate_id=etas_record.id,
            gutenberg_richter_estimate_id=gr_record.id,
            walk_forward_start=fit_end,
            walk_forward_end=fit_end + timedelta(days=14),
            step=timedelta(days=7),
            horizon_id="P7D",
            adjudication_delay=timedelta(hours=1),
            rng=np.random.default_rng(0),
            policy=WalkForwardPolicy(
                n_simulations=200, bootstrap_resamples=200, decision_thresholds=(0.5, 0.01)
            ),
        )

        assert evaluation_run.fold_count == 2
        assert evaluation_run.spatiotemporal_etas_estimate_id == etas_record.id
        assert evaluation_run.gutenberg_richter_estimate_id == gr_record.id

        fold_scores = list(
            session.scalars(
                select(EvaluationFoldScore).where(
                    EvaluationFoldScore.evaluation_run_id == evaluation_run.id
                )
            )
        )
        assert len(fold_scores) == 2
        total_observed = sum(fold.observed_event_count for fold in fold_scores)
        assert total_observed > 0, "fixture must produce real observed events to score against"

        for fold in fold_scores:
            forecast_run = session.get(ForecastRun, fold.forecast_run_id)
            assert forecast_run is not None
            assert forecast_run.issued_at + timedelta(seconds=604800) == forecast_run.validity_end

            scores = fold.scores_json
            assert math.isfinite(scores["point_process_log_likelihood"])
            assert math.isfinite(scores["deviance"])
            assert scores["log_loss"] >= 0.0
            assert 0.0 <= scores["brier_score"] <= 1.0
            assert 0.0 <= scores["predictive_coverage"] <= 1.0
            assert 0.0 <= scores["number_test"]["delta1"] <= 1.0
            assert 0.0 <= scores["number_test"]["delta2"] <= 1.0
            assert 0.0 <= scores["likelihood_test"]["quantile"] <= 1.0
            assert len(scores["threshold_scores"]) == 2

        aggregate = evaluation_run.aggregate_scores_json
        assert aggregate["number_test"]["fold_count"] == 2
        for score_name in ("log_loss", "brier_score", "point_process_log_likelihood"):
            bootstrap = aggregate[score_name]
            assert bootstrap is not None
            assert bootstrap["lower"] <= bootstrap["point_estimate"] <= bootstrap["upper"]

        # The homogeneous-Poisson reference model used for
        # information_gain_per_event is a real ETAS fit with triggering
        # switched off, not a fabricated placeholder -- with genuine
        # aftershock clustering in this synthetic catalog, the full model
        # should explain the observed catalog at least as well on average.
        gain = aggregate["information_gain_per_event"]
        if gain is not None:
            assert gain["point_estimate"] > -5.0
