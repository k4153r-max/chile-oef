"""One-off pipeline seed for a freshly-deployed environment: sync sources,
bulk-backfill real USGS history, build the production grid, then fit
Mc -> Gutenberg-Richter -> declustering -> background rate -> spatiotemporal
ETAS -> issue one forecast. Mirrors exactly the sequence run interactively
against the local dev database (see docs/PROJECT_STATE.md), as a single
script rather than chained CLI calls so intermediate ids never need to be
parsed from stdout. Intended to run from an environment with real internet
access to both the USGS API and the target database (GitHub Actions;
see .github/workflows/seed-production.yml) -- not part of the pytest suite.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from chile_oef.app.settings import get_settings
from chile_oef.db.models import SpatialGrid
from chile_oef.db.session import SessionLocal
from chile_oef.forecast.service import ForecastService
from chile_oef.forecast.simulation import CatalogSimulationPolicy
from chile_oef.forecast.specification import load_forecast_specification
from chile_oef.ingestion.historical_backfill import (
    BackfillBounds,
    BackfillPolicy,
    run_usgs_historical_backfill,
)
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import sync_source_registry
from chile_oef.seismicity.completeness import load_completeness_policy
from chile_oef.seismicity.service import (
    BackgroundRateService,
    CompletenessEstimationService,
    DeclusteringService,
    GutenbergRichterEstimationService,
    SpatiotemporalEtasService,
)
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasPolicy
from chile_oef.tectonics.grid import GridDefinition, GridService

CHILE_BOUNDS = BackfillBounds(
    min_latitude=-60, max_latitude=-15, min_longitude=-82, max_longitude=-62
)
GRID_ID = "chile_regular_0_1_v1"
FIT_START = datetime(2005, 1, 1, tzinfo=UTC)
FIT_END = datetime(2015, 1, 1, tzinfo=UTC)
MAGNITUDE_TYPE = "mb"


async def main() -> None:
    settings = get_settings()
    completeness_policy = load_completeness_policy(settings.completeness_policy_path)

    with SessionLocal() as session:
        print("== sync-sources ==", flush=True)
        sync_source_registry(session, load_source_registry(Path("config/source-registry.yaml")))

        print("== backfill USGS 1964 -> now ==", flush=True)
        summary = await run_usgs_historical_backfill(
            session,
            RawArchive(Path("data/raw")),
            start_time=datetime(1964, 1, 1, tzinfo=UTC),
            end_time=datetime.now(UTC),
            bounds=CHILE_BOUNDS,
            policy=BackfillPolicy(),
        )
        print(
            f"slices={summary.total_slices} succeeded={summary.succeeded_slices} "
            f"skipped={summary.skipped_already_done_slices} failed={len(summary.failed_slices)} "
            f"events_seen={summary.total_events_seen}",
            flush=True,
        )
        for start, end, message in summary.failed_slices:
            print(f"  FAILED slice {start}..{end}: {message}", flush=True)

        print("== init-grid ==", flush=True)
        grid = session.get(SpatialGrid, GRID_ID)
        if grid is None:
            grid = GridService(session).create(
                GridDefinition(
                    id=GRID_ID,
                    resolution_degrees=Decimal("0.1"),
                    min_latitude=Decimal("-60"),
                    max_latitude=Decimal("-15"),
                    min_longitude=Decimal("-82"),
                    max_longitude=Decimal("-62"),
                )
            )
        print(f"grid ready: {grid.id}", flush=True)

        print("== completeness (entire magnitude range) ==", flush=True)
        mc_record = CompletenessEstimationService(
            session, policy=completeness_policy
        ).estimate_entire_magnitude_range(
            as_of=datetime.now(UTC),
            start_time=FIT_START,
            end_time=FIT_END,
            magnitude_type=MAGNITUDE_TYPE,
            min_latitude=CHILE_BOUNDS.min_latitude,
            max_latitude=CHILE_BOUNDS.max_latitude,
            min_longitude=CHILE_BOUNDS.min_longitude,
            max_longitude=CHILE_BOUNDS.max_longitude,
        )
        print(
            f"mc={mc_record.mc_value} support_state={mc_record.support_state} id={mc_record.id}",
            flush=True,
        )
        if mc_record.support_state != "supported" or mc_record.mc_value is None:
            raise SystemExit(
                f"completeness estimate not supported (support_state="
                f"{mc_record.support_state!r}); aborting pipeline seed"
            )

        print("== Gutenberg-Richter ==", flush=True)
        gr_record = GutenbergRichterEstimationService(
            session, policy=completeness_policy
        ).estimate_for_completeness_estimate(mc_record.id)
        print(f"b_value={gr_record.b_value} id={gr_record.id}", flush=True)
        if gr_record.b_value is None:
            raise SystemExit("Gutenberg-Richter fit not supported; aborting pipeline seed")

        print("== declustering ==", flush=True)
        declustering_run = DeclusteringService(session).decluster_for_gutenberg_richter_estimate(
            gr_record.id
        )
        print(f"event_count={declustering_run.event_count} id={declustering_run.id}", flush=True)

        print("== background rate ==", flush=True)
        background_run = BackgroundRateService(session).estimate_for_declustering_run(
            declustering_run.id, GRID_ID
        )
        print(f"id={background_run.id}", flush=True)

        print("== spatiotemporal ETAS ==", flush=True)
        etas_record = SpatiotemporalEtasService(
            session, policy=SpatiotemporalEtasPolicy()
        ).estimate_for_completeness_estimate(mc_record.id, declustering_run_id=declustering_run.id)
        print(
            f"converged={etas_record.converged} support_state={etas_record.support_state} "
            f"id={etas_record.id}",
            flush=True,
        )
        if not etas_record.converged:
            raise SystemExit("spatiotemporal ETAS did not converge; aborting pipeline seed")

        print("== issue forecast ==", flush=True)
        specification = load_forecast_specification(settings.forecast_specification_path)
        run = ForecastService(
            session,
            specification=specification,
            simulation_policy=CatalogSimulationPolicy(),
        ).issue_forecast(
            spatiotemporal_etas_estimate_id=etas_record.id,
            gutenberg_richter_estimate_id=gr_record.id,
            background_rate_run_id=background_run.id,
            issued_at=datetime.now(UTC),
            horizon_id="P7D",
        )
        print(
            f"forecast_run_id={run.id} cells={run.cell_count} bins={run.magnitude_bin_count} "
            f"validity_end={run.validity_end}",
            flush=True,
        )

    print("== seed pipeline complete ==", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
