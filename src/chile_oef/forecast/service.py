import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from chile_oef.db.models import (
    CompletenessEstimate,
    ForecastCellMagnitudeBin,
    ForecastRun,
    GutenbergRichterEstimate,
    SeismicCell,
    SeismicCellBackgroundRate,
    SeismicityBackgroundRateRun,
    SeismicityDeclusteringRun,
    SpatialGrid,
    SpatiotemporalEtasEstimate,
)
from chile_oef.forecast.generation import ForecastGenerationPolicy, generate_forecast_cells
from chile_oef.forecast.simulation import (
    CatalogSimulationPolicy,
    simulate_predictive_catalog_counts,
)
from chile_oef.forecast.specification import ForecastSpecification, MagnitudeBin
from chile_oef.seismicity.background_rate import GridCellTarget
from chile_oef.seismicity.catalog_selection import fetch_declustering_catalog
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasParameters


@dataclass(frozen=True)
class GenerationInputs:
    """Everything `generate_forecast_cells` needs, assembled once from a
    specific spatiotemporal ETAS estimate, Gutenberg-Richter estimate and
    issue time. Shared between `ForecastService.issue_forecast` (which
    persists a real `ForecastRun`) and evaluation code that needs the same
    prior-catalog/cell inputs to score an alternative, non-persisted
    reference model (e.g. a homogeneous-Poisson baseline for information
    gain) without duplicating the catalog-fetch and lineage-consistency
    logic.
    """

    completeness_source: CompletenessEstimate
    etas_source: SpatiotemporalEtasEstimate
    gr_source: GutenbergRichterEstimate
    grid: SpatialGrid
    cell_targets: tuple[GridCellTarget, ...]
    magnitude_bins: tuple[MagnitudeBin, ...]
    etas_parameters: SpatiotemporalEtasParameters
    b_value: float
    reference_magnitude: float
    region_area_km2: float
    validity_start: datetime
    validity_end: datetime
    validity_start_days: float
    validity_end_days: float
    prior_event_times_days: tuple[float, ...]
    prior_event_latitudes: tuple[float, ...]
    prior_event_longitudes: tuple[float, ...]
    prior_event_magnitudes: tuple[float, ...]
    background_rate_run: SeismicityBackgroundRateRun | None
    background_cell_weights: dict[str, float] | None


class ForecastService:
    def __init__(
        self,
        session: Session,
        *,
        specification: ForecastSpecification,
        policy: ForecastGenerationPolicy | None = None,
        simulation_policy: CatalogSimulationPolicy | None = None,
    ) -> None:
        self.session = session
        self.specification = specification
        self.policy = policy or ForecastGenerationPolicy()
        self.simulation_policy = simulation_policy

    def prepare_generation_inputs(
        self,
        *,
        spatiotemporal_etas_estimate_id: uuid.UUID,
        gutenberg_richter_estimate_id: uuid.UUID,
        issued_at: datetime,
        horizon_id: str,
        background_rate_run_id: uuid.UUID | None = None,
    ) -> GenerationInputs:
        """Resolve and validate the ETAS/Gutenberg-Richter/completeness
        lineage, fetch the availability-safe prior catalog as of
        `issued_at`, and assemble everything `generate_forecast_cells`
        needs. Raises the same `ValueError`s `issue_forecast` always has:
        unknown estimate ids, non-convergent source estimates, or a
        Gutenberg-Richter estimate that does not share the ETAS estimate's
        completeness (Mc/window) lineage.
        """
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

        background_rate_run: SeismicityBackgroundRateRun | None = None
        background_cell_weights: dict[str, float] | None = None
        if background_rate_run_id is not None:
            background_rate_run = self.session.get(
                SeismicityBackgroundRateRun, background_rate_run_id
            )
            if background_rate_run is None:
                raise ValueError(f"background rate run {background_rate_run_id} not found")
            if background_rate_run.grid_id != grid.id:
                raise ValueError(
                    "background rate run and forecast specification reference different grids"
                )
            declustering_run = self.session.get(
                SeismicityDeclusteringRun, background_rate_run.declustering_run_id
            )
            if declustering_run is None:
                raise ValueError("background rate run references a missing declustering run")
            if declustering_run.gutenberg_richter_estimate_id != gr_source.id:
                raise ValueError(
                    "background rate run and forecast reference different Gutenberg-Richter "
                    "lineages"
                )
            background_rows = list(
                self.session.scalars(
                    select(SeismicCellBackgroundRate).where(
                        SeismicCellBackgroundRate.background_rate_run_id == background_rate_run.id
                    )
                )
            )
            background_cell_weights = {row.cell_id: row.rate_per_year for row in background_rows}

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

        return GenerationInputs(
            completeness_source=completeness_source,
            etas_source=etas_source,
            gr_source=gr_source,
            grid=grid,
            cell_targets=tuple(cell_targets),
            magnitude_bins=self.specification.magnitude_bins,
            etas_parameters=etas_parameters,
            b_value=gr_source.b_value,
            reference_magnitude=completeness_source.mc_value,
            region_area_km2=etas_source.region_area_km2,
            validity_start=validity_start,
            validity_end=validity_end,
            validity_start_days=validity_start_days,
            validity_end_days=validity_end_days,
            prior_event_times_days=tuple(prior_times_days),
            prior_event_latitudes=tuple(prior_lats),
            prior_event_longitudes=tuple(prior_lons),
            prior_event_magnitudes=tuple(prior_mags),
            background_rate_run=background_rate_run,
            background_cell_weights=background_cell_weights,
        )

    def issue_forecast(
        self,
        *,
        spatiotemporal_etas_estimate_id: uuid.UUID,
        gutenberg_richter_estimate_id: uuid.UUID,
        issued_at: datetime,
        horizon_id: str,
        trigger_type: str = "scheduled",
        supersedes_forecast_run_id: uuid.UUID | None = None,
        background_rate_run_id: uuid.UUID | None = None,
    ) -> ForecastRun:
        """Issue and persist one forecast (docs/forecast-contract.md). See
        `prepare_generation_inputs` for the lineage/availability rules this
        applies. A recalculation is a new call with
        `supersedes_forecast_run_id` set to the run it replaces; published
        rows are never updated or deleted (forecast-contract.md
        immutability).
        """
        inputs = self.prepare_generation_inputs(
            spatiotemporal_etas_estimate_id=spatiotemporal_etas_estimate_id,
            gutenberg_richter_estimate_id=gutenberg_richter_estimate_id,
            issued_at=issued_at,
            horizon_id=horizon_id,
            background_rate_run_id=background_rate_run_id,
        )

        result = generate_forecast_cells(
            prior_event_times_days=inputs.prior_event_times_days,
            prior_event_latitudes=inputs.prior_event_latitudes,
            prior_event_longitudes=inputs.prior_event_longitudes,
            prior_event_magnitudes=inputs.prior_event_magnitudes,
            etas_parameters=inputs.etas_parameters,
            b_value=inputs.b_value,
            reference_magnitude=inputs.reference_magnitude,
            region_area_km2=inputs.region_area_km2,
            validity_start_days=inputs.validity_start_days,
            validity_end_days=inputs.validity_end_days,
            cells=inputs.cell_targets,
            magnitude_bins=inputs.magnitude_bins,
            background_cell_weights=inputs.background_cell_weights,
            policy=self.policy,
        )
        diagnostics = dict(result.diagnostics)
        if self.simulation_policy is not None:
            simulation = simulate_predictive_catalog_counts(
                prior_event_times_days=inputs.prior_event_times_days,
                prior_event_magnitudes=inputs.prior_event_magnitudes,
                etas_parameters=inputs.etas_parameters,
                b_value=inputs.b_value,
                reference_magnitude=inputs.reference_magnitude,
                validity_start_days=inputs.validity_start_days,
                validity_end_days=inputs.validity_end_days,
                magnitude_bins=inputs.magnitude_bins,
                policy=self.simulation_policy,
            )
            diagnostics["predictive_catalog_simulation"] = simulation.as_dict()

        etas_source = inputs.etas_source
        gr_source = inputs.gr_source
        grid = inputs.grid
        cell_targets = inputs.cell_targets
        completeness_source = inputs.completeness_source
        validity_start = inputs.validity_start
        validity_end = inputs.validity_end

        run = ForecastRun(
            spatiotemporal_etas_estimate_id=etas_source.id,
            gutenberg_richter_estimate_id=gr_source.id,
            background_rate_run_id=(
                inputs.background_rate_run.id if inputs.background_rate_run is not None else None
            ),
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
            diagnostics_json=diagnostics,
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
