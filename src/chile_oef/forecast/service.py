import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from chile_oef.db.models import (
    CompletenessEstimate,
    ForecastCellMagnitudeBin,
    ForecastRun,
    GutenbergRichterEstimate,
    SeismicCell,
    SpatialGrid,
    SpatiotemporalEtasEstimate,
)
from chile_oef.forecast.generation import ForecastGenerationPolicy, generate_forecast_cells
from chile_oef.forecast.specification import ForecastSpecification
from chile_oef.seismicity.background_rate import GridCellTarget
from chile_oef.seismicity.catalog_selection import fetch_declustering_catalog
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasParameters


class ForecastService:
    def __init__(
        self,
        session: Session,
        *,
        specification: ForecastSpecification,
        policy: ForecastGenerationPolicy | None = None,
    ) -> None:
        self.session = session
        self.specification = specification
        self.policy = policy or ForecastGenerationPolicy()

    def issue_forecast(
        self,
        *,
        spatiotemporal_etas_estimate_id: uuid.UUID,
        gutenberg_richter_estimate_id: uuid.UUID,
        issued_at: datetime,
        horizon_id: str,
        trigger_type: str = "scheduled",
        supersedes_forecast_run_id: uuid.UUID | None = None,
    ) -> ForecastRun:
        """Issue one forecast (docs/forecast-contract.md): grid-cell x
        magnitude-bin rates and probabilities over [issued_at,
        issued_at + horizon), from a specific already-fit spatiotemporal
        ETAS estimate and a specific already-fit Gutenberg-Richter estimate.
        Both must trace back to the *same* CompletenessEstimate (same Mc,
        same window lineage) -- refused otherwise, rather than silently
        mixing a rate model and a magnitude-bin allocation fit to different
        Mc values. The input catalog snapshot used is everything available
        as of `issued_at` (the availability invariant: an input record
        participates only when its available_at is no later than
        issued_at), which may include events newer than what the cited
        Mc/b/ETAS estimates were originally fit on -- the model/parameter
        -set version and the input catalog snapshot are versioned
        independently, per forecast-contract.md.

        A recalculation is a new call with `supersedes_forecast_run_id` set
        to the run it replaces; published rows are never updated or
        deleted (docs/forecast-contract.md immutability).
        """
        etas_source = self.session.get(SpatiotemporalEtasEstimate, spatiotemporal_etas_estimate_id)
        if etas_source is None:
            raise ValueError(
                f"spatiotemporal ETAS estimate {spatiotemporal_etas_estimate_id} not found"
            )
        if etas_source.mu_per_day is None:
            raise ValueError(
                f"spatiotemporal ETAS estimate {spatiotemporal_etas_estimate_id} did not "
                f"converge (support_state={etas_source.support_state!r}); cannot issue a "
                "forecast from it"
            )

        gr_source = self.session.get(GutenbergRichterEstimate, gutenberg_richter_estimate_id)
        if gr_source is None:
            raise ValueError(
                f"gutenberg-richter estimate {gutenberg_richter_estimate_id} not found"
            )
        if gr_source.b_value is None:
            raise ValueError(
                f"gutenberg-richter estimate {gutenberg_richter_estimate_id} has no b_value "
                f"(support_state={gr_source.support_state!r}); cannot issue a forecast from it"
            )
        if gr_source.completeness_estimate_id != etas_source.completeness_estimate_id:
            raise ValueError(
                "gutenberg-richter estimate and spatiotemporal ETAS estimate reference "
                "different completeness estimates; a forecast must use one consistent "
                "Mc/window lineage"
            )

        completeness_source = self.session.get(
            CompletenessEstimate, etas_source.completeness_estimate_id
        )
        if completeness_source is None or completeness_source.mc_value is None:
            raise ValueError("referenced completeness estimate has no mc_value")

        horizon = self.specification.horizon(horizon_id)
        validity_start = issued_at
        validity_end = issued_at + timedelta(seconds=horizon.seconds)

        grid = self.session.get(SpatialGrid, self.specification.grid_id)
        if grid is None:
            raise ValueError(f"grid {self.specification.grid_id} not found")
        cells_orm = list(
            self.session.scalars(select(SeismicCell).where(SeismicCell.grid_id == grid.id))
        )
        if not cells_orm:
            raise ValueError(f"grid {grid.id} has no cells")
        cell_targets = [
            GridCellTarget(
                cell_id=cell.id,
                center_latitude=cell.center_latitude,
                center_longitude=cell.center_longitude,
                area_km2=cell.area_km2,
            )
            for cell in cells_orm
        ]

        observations = fetch_declustering_catalog(
            self.session,
            as_of=issued_at,
            start_time=completeness_source.start_time,
            end_time=issued_at,
            magnitude_type=completeness_source.magnitude_type,
            minimum_magnitude=completeness_source.mc_value,
            min_latitude=completeness_source.min_latitude,
            max_latitude=completeness_source.max_latitude,
            min_longitude=completeness_source.min_longitude,
            max_longitude=completeness_source.max_longitude,
        )
        ordered = sorted(observations, key=lambda observation: observation.event_time)
        prior_times_days = [
            (observation.event_time - completeness_source.start_time).total_seconds() / 86400.0
            for observation in ordered
        ]
        prior_lats = [observation.latitude for observation in ordered]
        prior_lons = [observation.longitude for observation in ordered]
        prior_mags = [observation.magnitude for observation in ordered]

        etas_parameters = SpatiotemporalEtasParameters(
            mu_per_day=etas_source.mu_per_day,
            k0=etas_source.k0,
            alpha=etas_source.alpha,
            c_days=etas_source.c_days,
            p_exponent=etas_source.p_exponent,
            d0_km=etas_source.d0_km,
            gamma=etas_source.gamma,
            q_exponent=etas_source.q_exponent,
        )
        validity_start_days = (
            validity_start - completeness_source.start_time
        ).total_seconds() / 86400.0
        validity_end_days = (
            validity_end - completeness_source.start_time
        ).total_seconds() / 86400.0

        result = generate_forecast_cells(
            prior_event_times_days=prior_times_days,
            prior_event_latitudes=prior_lats,
            prior_event_longitudes=prior_lons,
            prior_event_magnitudes=prior_mags,
            etas_parameters=etas_parameters,
            b_value=gr_source.b_value,
            reference_magnitude=completeness_source.mc_value,
            region_area_km2=etas_source.region_area_km2,
            validity_start_days=validity_start_days,
            validity_end_days=validity_end_days,
            cells=cell_targets,
            magnitude_bins=self.specification.magnitude_bins,
            policy=self.policy,
        )

        run = ForecastRun(
            spatiotemporal_etas_estimate_id=etas_source.id,
            gutenberg_richter_estimate_id=gr_source.id,
            grid_id=grid.id,
            supersedes_forecast_run_id=supersedes_forecast_run_id,
            trigger_type=trigger_type,
            issued_at=issued_at,
            validity_start=validity_start,
            validity_end=validity_end,
            horizon_id=horizon_id,
            reference_magnitude=completeness_source.mc_value,
            b_value_used=gr_source.b_value,
            region_area_km2=etas_source.region_area_km2,
            input_catalog_as_of=issued_at,
            method_version=result.method_version,
            calibration_status=result.calibration_status,
            cell_count=len(cell_targets),
            magnitude_bin_count=len(self.specification.magnitude_bins),
            diagnostics_json=result.diagnostics,
        )
        self.session.add(run)
        self.session.flush()

        self.session.add_all(
            ForecastCellMagnitudeBin(
                forecast_run_id=run.id,
                cell_id=cell_forecast.cell_id,
                magnitude_lower=cell_forecast.magnitude_lower,
                magnitude_upper=cell_forecast.magnitude_upper,
                support_state=cell_forecast.support_state,
                expected_count=cell_forecast.expected_count,
                probability_at_least_one=cell_forecast.probability_at_least_one,
            )
            for cell_forecast in result.cell_forecasts
        )
        self.session.commit()
        return run
