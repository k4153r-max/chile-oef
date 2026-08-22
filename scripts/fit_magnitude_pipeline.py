"""Fit Mc → Gutenberg-Richter → decluster → background → spatiotemporal
ETAS → one forecast, for a single native magnitude type, against an
already-ingested catalog.

Does not backfill, does not rebuild the grid, and does not update or delete
existing estimate rows. Intended for the moment-magnitude follow-up to the
first production ``mb`` fit (see research/b_value_mb_truncation.md).

Run from an environment that can reach the target Postgres (GitHub Actions
via CHILE_OEF_DATABASE_URL). Magnitude type is taken from
CHILE_OEF_FIT_MAGNITUDE_TYPE (default ``mwc``).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from chile_oef.app.settings import get_settings
from chile_oef.db.models import SpatialGrid
from chile_oef.db.session import SessionLocal
from chile_oef.forecast.service import ForecastService
from chile_oef.forecast.simulation import CatalogSimulationPolicy
from chile_oef.forecast.specification import load_forecast_specification
from chile_oef.seismicity.completeness import load_completeness_policy
from chile_oef.seismicity.service import (
    BackgroundRateService,
    CompletenessEstimationService,
    DeclusteringService,
    GutenbergRichterEstimationService,
    SpatiotemporalEtasService,
)
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasPolicy

CHILE_BOUNDS = {
    "min_latitude": -60.0,
    "max_latitude": -15.0,
    "min_longitude": -82.0,
    "max_longitude": -62.0,
}
GRID_ID = "chile_regular_0_1_v1"
FIT_START = datetime(2005, 1, 1, tzinfo=UTC)
FIT_END = datetime(2015, 1, 1, tzinfo=UTC)
DEFAULT_MAGNITUDE_TYPE = "mwc"


def main() -> None:
    magnitude_type = os.environ.get("CHILE_OEF_FIT_MAGNITUDE_TYPE", DEFAULT_MAGNITUDE_TYPE).strip()
    if not magnitude_type:
        raise SystemExit("CHILE_OEF_FIT_MAGNITUDE_TYPE is empty")

    settings = get_settings()
    completeness_policy = load_completeness_policy(settings.completeness_policy_path)

    with SessionLocal() as session:
        grid = session.get(SpatialGrid, GRID_ID)
        if grid is None:
            raise SystemExit(f"grid {GRID_ID} is missing; run the production seed before this fit")
        print(f"== grid {grid.id} ==", flush=True)
        print(
            f"== magnitude_type={magnitude_type} window={FIT_START.date()}..{FIT_END.date()} ==",
            flush=True,
        )

        print("== completeness (entire magnitude range) ==", flush=True)
        mc_record = CompletenessEstimationService(
            session, policy=completeness_policy
        ).estimate_entire_magnitude_range(
            as_of=datetime.now(UTC),
            start_time=FIT_START,
            end_time=FIT_END,
            magnitude_type=magnitude_type,
            **CHILE_BOUNDS,
        )
        print(
            f"mc={mc_record.mc_value} support_state={mc_record.support_state} "
            f"event_count={mc_record.event_count} id={mc_record.id}",
            flush=True,
        )
        if mc_record.support_state != "supported" or mc_record.mc_value is None:
            raise SystemExit(
                f"completeness estimate not supported (support_state="
                f"{mc_record.support_state!r}); aborting"
            )

        print("== Gutenberg-Richter ==", flush=True)
        gr_record = GutenbergRichterEstimationService(
            session, policy=completeness_policy
        ).estimate_for_completeness_estimate(mc_record.id)
        print(
            f"b_value={gr_record.b_value} se={gr_record.b_value_standard_error} "
            f"n_above={gr_record.events_at_or_above_mc} "
            f"limited={gr_record.diagnostics_json.get('limited_dynamic_range')} "
            f"unusual={gr_record.diagnostics_json.get('unusual_b_value')} "
            f"id={gr_record.id}",
            flush=True,
        )
        if gr_record.b_value is None:
            raise SystemExit("Gutenberg-Richter fit not supported; aborting")
        if gr_record.diagnostics_json.get("limited_dynamic_range"):
            raise SystemExit(
                "Gutenberg-Richter reports limited_dynamic_range; "
                "refusing to promote this magnitude type to the live forecast"
            )

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
            raise SystemExit("spatiotemporal ETAS did not converge; aborting")

        print("== issue forecast ==", flush=True)
        specification = load_forecast_specification(Path(settings.forecast_specification_path))
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
            f"b_value_used={run.b_value_used} reference_magnitude={run.reference_magnitude} "
            f"validity_end={run.validity_end}",
            flush=True,
        )

    print("== magnitude-type pipeline complete ==", flush=True)


if __name__ == "__main__":
    main()
