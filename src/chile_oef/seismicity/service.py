import math
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from chile_oef.db.models import (
    CompletenessEstimate,
    EventDeclusteringClassification,
    EventRevision,
    GutenbergRichterEstimate,
    ModifiedOmoriSequenceEstimate,
    SeismicAnomalyIndexEstimate,
    SeismicCell,
    SeismicCellBackgroundRate,
    SeismicityBackgroundRateRun,
    SeismicityDeclusteringRun,
    SpatialGrid,
    SpatiotemporalEtasEstimate,
    TemporalEtasEstimate,
)
from chile_oef.seismicity.background_rate import (
    BackgroundEventLocation,
    BackgroundRatePolicy,
    GridCellTarget,
    estimate_background_rate,
)
from chile_oef.seismicity.catalog_selection import (
    CatalogSelection,
    fetch_declustering_catalog,
    fetch_magnitude_catalog,
)
from chile_oef.seismicity.completeness import (
    CompletenessPolicy,
    estimate_mc_entire_magnitude_range,
    estimate_mc_goodness_of_fit,
    estimate_mc_maximum_curvature,
)
from chile_oef.seismicity.declustering import (
    DeclusteringPolicy,
    EventForDeclustering,
    decluster,
)
from chile_oef.seismicity.etas import EtasParameters, EtasPolicy, estimate_temporal_etas
from chile_oef.seismicity.gutenberg_richter import estimate_b_value
from chile_oef.seismicity.ias import IasPolicy, estimate_ias
from chile_oef.seismicity.modified_omori import ModifiedOmoriPolicy, estimate_modified_omori
from chile_oef.seismicity.spatiotemporal_etas import (
    SpatiotemporalEtasParameters,
    SpatiotemporalEtasPolicy,
    estimate_spatiotemporal_etas,
)

EARTH_RADIUS_KM = 6371.0088


class CompletenessEstimationService:
    def __init__(self, session: Session, *, policy: CompletenessPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or CompletenessPolicy()

    def _select(
        self,
        *,
        as_of: datetime,
        start_time: datetime,
        end_time: datetime,
        magnitude_type: str,
        min_latitude: float | None,
        max_latitude: float | None,
        min_longitude: float | None,
        max_longitude: float | None,
    ) -> CatalogSelection:
        return fetch_magnitude_catalog(
            self.session,
            as_of=as_of,
            start_time=start_time,
            end_time=end_time,
            magnitude_type=magnitude_type,
            min_latitude=min_latitude,
            max_latitude=max_latitude,
            min_longitude=min_longitude,
            max_longitude=max_longitude,
        )

    def estimate_maximum_curvature(
        self,
        *,
        as_of: datetime,
        start_time: datetime,
        end_time: datetime,
        magnitude_type: str,
        min_latitude: float | None = None,
        max_latitude: float | None = None,
        min_longitude: float | None = None,
        max_longitude: float | None = None,
    ) -> CompletenessEstimate:
        selection = self._select(
            as_of=as_of,
            start_time=start_time,
            end_time=end_time,
            magnitude_type=magnitude_type,
            min_latitude=min_latitude,
            max_latitude=max_latitude,
            min_longitude=min_longitude,
            max_longitude=max_longitude,
        )
        result = estimate_mc_maximum_curvature(
            [observation.magnitude for observation in selection.observations],
            policy=self.policy,
        )
        record = CompletenessEstimate(
            start_time=start_time,
            end_time=end_time,
            min_latitude=min_latitude,
            max_latitude=max_latitude,
            min_longitude=min_longitude,
            max_longitude=max_longitude,
            magnitude_type=magnitude_type,
            method_version=result.method_version,
            role=result.role,
            calibration_status=result.calibration_status,
            event_count=result.event_count,
            support_state=result.support_state,
            mc_value=result.mc_value,
            bin_width_magnitude=result.bin_width_magnitude,
            catalog_as_of=selection.catalog_as_of,
            diagnostics_json={
                **result.diagnostics,
                "raw_peak_bin_magnitude": result.raw_peak_bin_magnitude,
            },
        )
        self.session.add(record)
        self.session.commit()
        return record

    def estimate_goodness_of_fit(
        self,
        *,
        as_of: datetime,
        start_time: datetime,
        end_time: datetime,
        magnitude_type: str,
        min_latitude: float | None = None,
        max_latitude: float | None = None,
        min_longitude: float | None = None,
        max_longitude: float | None = None,
    ) -> CompletenessEstimate:
        selection = self._select(
            as_of=as_of,
            start_time=start_time,
            end_time=end_time,
            magnitude_type=magnitude_type,
            min_latitude=min_latitude,
            max_latitude=max_latitude,
            min_longitude=min_longitude,
            max_longitude=max_longitude,
        )
        result = estimate_mc_goodness_of_fit(
            [observation.magnitude for observation in selection.observations],
            policy=self.policy,
        )
        record = CompletenessEstimate(
            start_time=start_time,
            end_time=end_time,
            min_latitude=min_latitude,
            max_latitude=max_latitude,
            min_longitude=min_longitude,
            max_longitude=max_longitude,
            magnitude_type=magnitude_type,
            method_version=result.method_version,
            role=result.role,
            calibration_status=result.calibration_status,
            event_count=result.event_count,
            support_state=result.support_state,
            mc_value=result.mc_value,
            bin_width_magnitude=result.bin_width_magnitude,
            catalog_as_of=selection.catalog_as_of,
            diagnostics_json={
                **result.diagnostics,
                "achieved_confidence_percent": result.achieved_confidence_percent,
                "best_fit_quality_percent": result.best_fit_quality_percent,
            },
        )
        self.session.add(record)
        self.session.commit()
        return record

    def estimate_entire_magnitude_range(
        self,
        *,
        as_of: datetime,
        start_time: datetime,
        end_time: datetime,
        magnitude_type: str,
        min_latitude: float | None = None,
        max_latitude: float | None = None,
        min_longitude: float | None = None,
        max_longitude: float | None = None,
    ) -> CompletenessEstimate:
        selection = self._select(
            as_of=as_of,
            start_time=start_time,
            end_time=end_time,
            magnitude_type=magnitude_type,
            min_latitude=min_latitude,
            max_latitude=max_latitude,
            min_longitude=min_longitude,
            max_longitude=max_longitude,
        )
        result = estimate_mc_entire_magnitude_range(
            [observation.magnitude for observation in selection.observations],
            policy=self.policy,
        )
        record = CompletenessEstimate(
            start_time=start_time,
            end_time=end_time,
            min_latitude=min_latitude,
            max_latitude=max_latitude,
            min_longitude=min_longitude,
            max_longitude=max_longitude,
            magnitude_type=magnitude_type,
            method_version=result.method_version,
            role=result.role,
            calibration_status=result.calibration_status,
            event_count=result.event_count,
            support_state=result.support_state,
            mc_value=result.mc_value,
            bin_width_magnitude=result.bin_width_magnitude,
            catalog_as_of=selection.catalog_as_of,
            diagnostics_json={
                **result.diagnostics,
                "mc_confidence_interval": result.mc_confidence_interval,
                "detection_sigma_magnitude": result.detection_sigma_magnitude,
                "b_value": result.b_value,
                "converged": result.converged,
                "bootstrap_resamples_converged": result.bootstrap_resamples_converged,
            },
        )
        self.session.add(record)
        self.session.commit()
        return record


class GutenbergRichterEstimationService:
    def __init__(self, session: Session, *, policy: CompletenessPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or CompletenessPolicy()

    def estimate_for_completeness_estimate(
        self, completeness_estimate_id: uuid.UUID
    ) -> GutenbergRichterEstimate:
        """Fit b above the Mc of a specific, already-persisted completeness
        estimate. The window, magnitude type, and spatial filters are taken
        from that row rather than accepted as separate arguments, so this
        can never be pointed at a Mc from a mismatched window or region.
        """
        source = self.session.get(CompletenessEstimate, completeness_estimate_id)
        if source is None:
            raise ValueError(f"completeness estimate {completeness_estimate_id} not found")
        if source.mc_value is None:
            raise ValueError(
                f"completeness estimate {completeness_estimate_id} has no mc_value "
                f"(support_state={source.support_state!r}); cannot fit Gutenberg-Richter on it"
            )

        selection = fetch_magnitude_catalog(
            self.session,
            as_of=source.catalog_as_of,
            start_time=source.start_time,
            end_time=source.end_time,
            magnitude_type=source.magnitude_type,
            min_latitude=source.min_latitude,
            max_latitude=source.max_latitude,
            min_longitude=source.min_longitude,
            max_longitude=source.max_longitude,
        )
        result = estimate_b_value(
            [observation.magnitude for observation in selection.observations],
            mc=source.mc_value,
            policy=self.policy,
        )
        record = GutenbergRichterEstimate(
            completeness_estimate_id=source.id,
            start_time=source.start_time,
            end_time=source.end_time,
            min_latitude=source.min_latitude,
            max_latitude=source.max_latitude,
            min_longitude=source.min_longitude,
            max_longitude=source.max_longitude,
            magnitude_type=source.magnitude_type,
            mc_used=result.mc_used,
            method_version=result.method_version,
            calibration_status=result.calibration_status,
            event_count=result.event_count,
            events_at_or_above_mc=result.events_at_or_above_mc,
            support_state=result.support_state,
            b_value=result.b_value,
            b_value_standard_error=result.b_value_standard_error,
            a_value=result.a_value,
            catalog_as_of=selection.catalog_as_of,
            diagnostics_json=result.diagnostics,
        )
        self.session.add(record)
        self.session.commit()
        return record


class DeclusteringService:
    def __init__(self, session: Session, *, policy: DeclusteringPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or DeclusteringPolicy()

    def decluster_for_gutenberg_richter_estimate(
        self, gutenberg_richter_estimate_id: uuid.UUID
    ) -> SeismicityDeclusteringRun:
        """Decluster the catalog at/above a specific Gutenberg-Richter
        estimate's Mc, using its b_value in the nearest-neighbor metric. The
        window, magnitude type, spatial filters, and minimum magnitude are
        all taken from that row -- same structural-provenance pattern as
        GutenbergRichterEstimationService.
        """
        source = self.session.get(GutenbergRichterEstimate, gutenberg_richter_estimate_id)
        if source is None:
            raise ValueError(
                f"gutenberg-richter estimate {gutenberg_richter_estimate_id} not found"
            )
        if source.b_value is None:
            raise ValueError(
                f"gutenberg-richter estimate {gutenberg_richter_estimate_id} has no b_value "
                f"(support_state={source.support_state!r}); cannot decluster on it"
            )

        observations = fetch_declustering_catalog(
            self.session,
            as_of=source.catalog_as_of,
            start_time=source.start_time,
            end_time=source.end_time,
            magnitude_type=source.magnitude_type,
            minimum_magnitude=source.mc_used,
            min_latitude=source.min_latitude,
            max_latitude=source.max_latitude,
            min_longitude=source.min_longitude,
            max_longitude=source.max_longitude,
        )
        events_for_declustering = [
            EventForDeclustering(
                event_id=observation.event_revision_id,
                event_time=observation.event_time,
                latitude=observation.latitude,
                longitude=observation.longitude,
                magnitude=observation.magnitude,
            )
            for observation in observations
        ]
        result = decluster(events_for_declustering, b_value=source.b_value, policy=self.policy)

        run = SeismicityDeclusteringRun(
            gutenberg_richter_estimate_id=source.id,
            start_time=source.start_time,
            end_time=source.end_time,
            min_latitude=source.min_latitude,
            max_latitude=source.max_latitude,
            min_longitude=source.min_longitude,
            max_longitude=source.max_longitude,
            magnitude_type=source.magnitude_type,
            minimum_magnitude=source.mc_used,
            b_value_used=source.b_value,
            fractal_dimension=result.fractal_dimension,
            method_version=result.method_version,
            calibration_status=result.calibration_status,
            event_count=result.event_count,
            classified_event_count=result.classified_event_count,
            background_event_count=result.background_event_count,
            log_eta_threshold=result.log_eta_threshold,
            catalog_as_of=source.catalog_as_of,
            diagnostics_json=result.diagnostics,
        )
        self.session.add(run)
        self.session.flush()

        self.session.add_all(
            EventDeclusteringClassification(
                declustering_run_id=run.id,
                event_revision_id=classification.event_id,
                parent_event_revision_id=classification.parent_event_id,
                log10_eta=classification.log10_eta,
                is_background=classification.is_background,
            )
            for classification in result.classifications
        )
        self.session.commit()
        return run


class BackgroundRateService:
    def __init__(self, session: Session, *, policy: BackgroundRatePolicy | None = None) -> None:
        self.session = session
        self.policy = policy or BackgroundRatePolicy()

    def estimate_for_declustering_run(
        self, declustering_run_id: uuid.UUID, grid_id: str
    ) -> SeismicityBackgroundRateRun:
        """Smooth the background subset of a specific declustering run's
        event classifications over a specific Phase 2 grid. Both are
        required, explicit references -- there is no "current" run or grid.
        """
        run = self.session.get(SeismicityDeclusteringRun, declustering_run_id)
        if run is None:
            raise ValueError(f"declustering run {declustering_run_id} not found")
        grid = self.session.get(SpatialGrid, grid_id)
        if grid is None:
            raise ValueError(f"grid {grid_id} not found")

        background_rows = self.session.execute(
            select(EventRevision.latitude, EventRevision.longitude)
            .join(
                EventDeclusteringClassification,
                EventDeclusteringClassification.event_revision_id == EventRevision.id,
            )
            .where(
                EventDeclusteringClassification.declustering_run_id == run.id,
                EventDeclusteringClassification.is_background.is_(True),
            )
        ).all()
        locations = [
            BackgroundEventLocation(latitude=latitude, longitude=longitude)
            for latitude, longitude in background_rows
        ]

        cells = list(
            self.session.scalars(select(SeismicCell).where(SeismicCell.grid_id == grid_id))
        )
        cell_targets = [
            GridCellTarget(
                cell_id=cell.id,
                center_latitude=cell.center_latitude,
                center_longitude=cell.center_longitude,
                area_km2=cell.area_km2,
            )
            for cell in cells
        ]

        observation_duration_days = (run.end_time - run.start_time).total_seconds() / 86400.0
        result = estimate_background_rate(
            locations,
            cell_targets,
            observation_duration_days=observation_duration_days,
            policy=self.policy,
        )

        background_rate_run = SeismicityBackgroundRateRun(
            declustering_run_id=run.id,
            grid_id=grid_id,
            k_nearest_neighbors=result.k_nearest_neighbors,
            minimum_bandwidth_km=self.policy.minimum_bandwidth_km,
            observation_duration_days=result.observation_duration_days,
            background_event_count=result.background_event_count,
            method_version=result.method_version,
            calibration_status=result.calibration_status,
            catalog_as_of=run.catalog_as_of,
            diagnostics_json=result.diagnostics,
        )
        self.session.add(background_rate_run)
        self.session.flush()

        self.session.add_all(
            SeismicCellBackgroundRate(
                background_rate_run_id=background_rate_run.id,
                cell_id=cell_rate.cell_id,
                density_per_km2=cell_rate.density_per_km2,
                rate_per_year=cell_rate.rate_per_year,
            )
            for cell_rate in result.cell_rates
        )
        self.session.commit()
        return background_rate_run


def _resolve_family_roots(
    classifications: list[tuple[uuid.UUID, uuid.UUID | None, bool | None]],
) -> dict[uuid.UUID, uuid.UUID]:
    """For every triggered event, walk its parent chain (as recorded by
    declustering) up to the nearest background ancestor -- that ancestor is
    the family root every event in one aftershock sequence shares, even
    across secondary triggering (an aftershock triggering its own
    aftershock). Returns {triggered_event_id: family_root_id}.
    """
    parent_by_id = {event_id: parent_id for event_id, parent_id, _is_background in classifications}
    is_background_by_id = {
        event_id: is_background for event_id, _parent_id, is_background in classifications
    }
    family_root_by_id: dict[uuid.UUID, uuid.UUID] = {}
    for event_id, _parent_id, is_background in classifications:
        if is_background is not False:
            continue
        current = event_id
        while is_background_by_id.get(current) is False:
            parent = parent_by_id.get(current)
            if parent is None:
                break
            current = parent
        if is_background_by_id.get(current) is True:
            family_root_by_id[event_id] = current
    return family_root_by_id


class ModifiedOmoriService:
    def __init__(self, session: Session, *, policy: ModifiedOmoriPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or ModifiedOmoriPolicy()

    def estimate_for_declustering_run(
        self, declustering_run_id: uuid.UUID
    ) -> list[ModifiedOmoriSequenceEstimate]:
        """Fit a Modified Omori-Utsu sequence for every aftershock family
        (grouped by root ancestor, see _resolve_family_roots) in a specific
        declustering run with at least one triggered event. Families below
        the minimum sample size still get a not_estimable row, for the same
        auditability reason every other estimator here persists refusals.
        """
        run = self.session.get(SeismicityDeclusteringRun, declustering_run_id)
        if run is None:
            raise ValueError(f"declustering run {declustering_run_id} not found")

        rows = self.session.execute(
            select(
                EventDeclusteringClassification.event_revision_id,
                EventDeclusteringClassification.parent_event_revision_id,
                EventDeclusteringClassification.is_background,
            ).where(EventDeclusteringClassification.declustering_run_id == run.id)
        ).all()
        family_root_by_event_id = _resolve_family_roots([tuple(row) for row in rows])

        children_by_root: dict[uuid.UUID, list[uuid.UUID]] = {}
        for event_id, root_id in family_root_by_event_id.items():
            children_by_root.setdefault(root_id, []).append(event_id)

        if not children_by_root:
            return []

        event_ids = set(children_by_root.keys())
        for children in children_by_root.values():
            event_ids.update(children)
        event_times_by_id = dict(
            self.session.execute(
                select(EventRevision.id, EventRevision.event_time).where(
                    EventRevision.id.in_(event_ids)
                )
            ).all()
        )

        records: list[ModifiedOmoriSequenceEstimate] = []
        for root_id, children in children_by_root.items():
            root_time = event_times_by_id[root_id]
            observation_duration_days = (run.end_time - root_time).total_seconds() / 86400.0
            event_times_days = sorted(
                (event_times_by_id[child_id] - root_time).total_seconds() / 86400.0
                for child_id in children
            )
            result = estimate_modified_omori(
                event_times_days,
                observation_duration_days=observation_duration_days,
                policy=self.policy,
            )
            record = ModifiedOmoriSequenceEstimate(
                declustering_run_id=run.id,
                root_event_revision_id=root_id,
                event_count=result.event_count,
                support_state=result.support_state,
                observation_duration_days=result.observation_duration_days,
                k_productivity=result.k_productivity,
                c_days=result.c_days,
                p_exponent=result.p_exponent,
                converged=result.converged,
                method_version=result.method_version,
                calibration_status=result.calibration_status,
                diagnostics_json=result.diagnostics,
            )
            self.session.add(record)
            records.append(record)
        self.session.commit()
        return records


class TemporalEtasService:
    def __init__(self, session: Session, *, policy: EtasPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or EtasPolicy()

    def _resolve_initial_guess(
        self, declustering_run_id: uuid.UUID | None, *, event_count: int, duration_days: float
    ) -> tuple[EtasParameters | None, uuid.UUID | None]:
        """Average (K, c, p) over a declustering run's estimable Modified
        Omori families, weighted by family size, per
        docs/PROJECT_STATE.md's guidance that ETAS should build on that
        baseline rather than fit blind. Purely a starting point for the
        optimizer -- ETAS does not require declustering to run, so a
        missing or empty run just falls back to a crude guess.
        """
        if declustering_run_id is None:
            return None, None
        omori_rows = list(
            self.session.scalars(
                select(ModifiedOmoriSequenceEstimate).where(
                    ModifiedOmoriSequenceEstimate.declustering_run_id == declustering_run_id,
                    ModifiedOmoriSequenceEstimate.support_state == "estimable",
                )
            )
        )
        if not omori_rows:
            return None, None
        total_weight = sum(row.event_count for row in omori_rows)
        k0 = sum(row.k_productivity * row.event_count for row in omori_rows) / total_weight
        c = sum(row.c_days * row.event_count for row in omori_rows) / total_weight
        p = sum(row.p_exponent * row.event_count for row in omori_rows) / total_weight
        crude_mu = max(event_count / duration_days / 2.0, 1e-6)
        seed_row = max(omori_rows, key=lambda row: row.event_count)
        return EtasParameters(
            mu_per_day=crude_mu, k0=k0, alpha=1.0, c_days=c, p_exponent=p
        ), seed_row.id

    def estimate_for_completeness_estimate(
        self,
        completeness_estimate_id: uuid.UUID,
        *,
        declustering_run_id: uuid.UUID | None = None,
    ) -> TemporalEtasEstimate:
        """Fit temporal ETAS on the catalog at/above a specific completeness
        estimate's Mc. If `declustering_run_id` is given, its estimable
        Modified Omori families seed the optimizer's starting point (see
        _resolve_initial_guess); this is a soft, documented reference, not
        a required dependency.
        """
        source = self.session.get(CompletenessEstimate, completeness_estimate_id)
        if source is None:
            raise ValueError(f"completeness estimate {completeness_estimate_id} not found")
        if source.mc_value is None:
            raise ValueError(
                f"completeness estimate {completeness_estimate_id} has no mc_value "
                f"(support_state={source.support_state!r}); cannot fit ETAS on it"
            )

        selection = fetch_magnitude_catalog(
            self.session,
            as_of=source.catalog_as_of,
            start_time=source.start_time,
            end_time=source.end_time,
            magnitude_type=source.magnitude_type,
            min_latitude=source.min_latitude,
            max_latitude=source.max_latitude,
            min_longitude=source.min_longitude,
            max_longitude=source.max_longitude,
        )
        above_mc = [
            observation
            for observation in selection.observations
            if observation.magnitude >= source.mc_value
        ]
        above_mc.sort(key=lambda observation: observation.event_time)
        duration_days = (source.end_time - source.start_time).total_seconds() / 86400.0
        event_times_days = [
            (observation.event_time - source.start_time).total_seconds() / 86400.0
            for observation in above_mc
        ]
        magnitudes = [observation.magnitude for observation in above_mc]

        initial_guess, initial_guess_source_id = self._resolve_initial_guess(
            declustering_run_id, event_count=len(above_mc), duration_days=duration_days
        )

        result = estimate_temporal_etas(
            event_times_days,
            magnitudes,
            reference_magnitude=source.mc_value,
            observation_duration_days=duration_days,
            policy=self.policy,
            initial_guess=initial_guess,
        )

        parameters = result.parameters
        record = TemporalEtasEstimate(
            completeness_estimate_id=source.id,
            initial_guess_source_id=initial_guess_source_id,
            start_time=source.start_time,
            end_time=source.end_time,
            min_latitude=source.min_latitude,
            max_latitude=source.max_latitude,
            min_longitude=source.min_longitude,
            max_longitude=source.max_longitude,
            magnitude_type=source.magnitude_type,
            reference_magnitude=result.reference_magnitude,
            event_count=result.event_count,
            support_state=result.support_state,
            observation_duration_days=result.observation_duration_days,
            mu_per_day=parameters.mu_per_day if parameters else None,
            k0=parameters.k0 if parameters else None,
            alpha=parameters.alpha if parameters else None,
            c_days=parameters.c_days if parameters else None,
            p_exponent=parameters.p_exponent if parameters else None,
            converged=result.converged,
            restarts_converged=result.restarts_converged,
            log_likelihood=result.log_likelihood,
            method_version=result.method_version,
            calibration_status=result.calibration_status,
            catalog_as_of=source.catalog_as_of,
            diagnostics_json=result.diagnostics,
        )
        self.session.add(record)
        self.session.commit()
        return record


def _region_area_km2(
    min_latitude: float, max_latitude: float, min_longitude: float, max_longitude: float
) -> float:
    mid_latitude_radians = math.radians((min_latitude + max_latitude) / 2.0)
    height_km = (max_latitude - min_latitude) * (math.pi / 180.0) * EARTH_RADIUS_KM
    width_km = (
        (max_longitude - min_longitude)
        * (math.pi / 180.0)
        * EARTH_RADIUS_KM
        * math.cos(mid_latitude_radians)
    )
    return abs(height_km * width_km)


class SpatiotemporalEtasService:
    def __init__(self, session: Session, *, policy: SpatiotemporalEtasPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or SpatiotemporalEtasPolicy()

    def _resolve_initial_guess(
        self, declustering_run_id: uuid.UUID | None
    ) -> tuple[SpatiotemporalEtasParameters | None, uuid.UUID | None]:
        if declustering_run_id is None:
            return None, None
        omori_rows = list(
            self.session.scalars(
                select(ModifiedOmoriSequenceEstimate).where(
                    ModifiedOmoriSequenceEstimate.declustering_run_id == declustering_run_id,
                    ModifiedOmoriSequenceEstimate.support_state == "estimable",
                )
            )
        )
        if not omori_rows:
            return None, None
        total_weight = sum(row.event_count for row in omori_rows)
        c = sum(row.c_days * row.event_count for row in omori_rows) / total_weight
        p = sum(row.p_exponent * row.event_count for row in omori_rows) / total_weight
        seed_row = max(omori_rows, key=lambda row: row.event_count)
        # k0/mu are not meaningfully transferable from a temporal-only fit
        # to a spatial-density-valued one (different units, see
        # spatiotemporal_etas.py); only (c, p) -- the purely temporal shape
        # -- are reused, with generic defaults for the rest.
        return (
            SpatiotemporalEtasParameters(
                mu_per_day=1.0,
                k0=1.0,
                alpha=1.0,
                c_days=c,
                p_exponent=p,
                d0_km=5.0,
                gamma=0.5,
                q_exponent=1.5,
            ),
            seed_row.id,
        )

    def estimate_for_completeness_estimate(
        self,
        completeness_estimate_id: uuid.UUID,
        *,
        declustering_run_id: uuid.UUID | None = None,
    ) -> SpatiotemporalEtasEstimate:
        """Fit spatiotemporal ETAS on the catalog at/above a specific
        completeness estimate's Mc, within its bounding box (required --
        spatiotemporal ETAS needs a defined region; a completeness estimate
        without one is refused rather than guessing a default area).
        """
        source = self.session.get(CompletenessEstimate, completeness_estimate_id)
        if source is None:
            raise ValueError(f"completeness estimate {completeness_estimate_id} not found")
        if source.mc_value is None:
            raise ValueError(
                f"completeness estimate {completeness_estimate_id} has no mc_value "
                f"(support_state={source.support_state!r}); cannot fit ETAS on it"
            )
        if None in (
            source.min_latitude,
            source.max_latitude,
            source.min_longitude,
            source.max_longitude,
        ):
            raise ValueError(
                f"completeness estimate {completeness_estimate_id} has no bounding box; "
                "spatiotemporal ETAS requires a defined region"
            )

        observations = fetch_declustering_catalog(
            self.session,
            as_of=source.catalog_as_of,
            start_time=source.start_time,
            end_time=source.end_time,
            magnitude_type=source.magnitude_type,
            minimum_magnitude=source.mc_value,
            min_latitude=source.min_latitude,
            max_latitude=source.max_latitude,
            min_longitude=source.min_longitude,
            max_longitude=source.max_longitude,
        )
        ordered = sorted(observations, key=lambda observation: observation.event_time)
        duration_days = (source.end_time - source.start_time).total_seconds() / 86400.0
        event_times_days = [
            (observation.event_time - source.start_time).total_seconds() / 86400.0
            for observation in ordered
        ]
        latitudes = [observation.latitude for observation in ordered]
        longitudes = [observation.longitude for observation in ordered]
        magnitudes = [observation.magnitude for observation in ordered]
        region_area_km2 = _region_area_km2(
            source.min_latitude, source.max_latitude, source.min_longitude, source.max_longitude
        )

        initial_guess, initial_guess_source_id = self._resolve_initial_guess(declustering_run_id)

        result = estimate_spatiotemporal_etas(
            event_times_days,
            latitudes,
            longitudes,
            magnitudes,
            region_area_km2=region_area_km2,
            reference_magnitude=source.mc_value,
            observation_duration_days=duration_days,
            policy=self.policy,
            initial_guess=initial_guess,
        )

        parameters = result.parameters
        record = SpatiotemporalEtasEstimate(
            completeness_estimate_id=source.id,
            initial_guess_source_id=initial_guess_source_id,
            start_time=source.start_time,
            end_time=source.end_time,
            min_latitude=source.min_latitude,
            max_latitude=source.max_latitude,
            min_longitude=source.min_longitude,
            max_longitude=source.max_longitude,
            region_area_km2=region_area_km2,
            magnitude_type=source.magnitude_type,
            reference_magnitude=result.reference_magnitude,
            event_count=result.event_count,
            support_state=result.support_state,
            observation_duration_days=result.observation_duration_days,
            mu_per_day=parameters.mu_per_day if parameters else None,
            k0=parameters.k0 if parameters else None,
            alpha=parameters.alpha if parameters else None,
            c_days=parameters.c_days if parameters else None,
            p_exponent=parameters.p_exponent if parameters else None,
            d0_km=parameters.d0_km if parameters else None,
            gamma=parameters.gamma if parameters else None,
            q_exponent=parameters.q_exponent if parameters else None,
            converged=result.converged,
            restarts_converged=result.restarts_converged,
            log_likelihood=result.log_likelihood,
            method_version=result.method_version,
            calibration_status=result.calibration_status,
            catalog_as_of=source.catalog_as_of,
            diagnostics_json=result.diagnostics,
        )
        self.session.add(record)
        self.session.commit()
        return record


class IasEstimationService:
    def __init__(self, session: Session, *, policy: IasPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or IasPolicy()

    def estimate_for_temporal_etas_estimate(
        self, temporal_etas_estimate_id: uuid.UUID, *, evaluation_end_at: datetime
    ) -> SeismicAnomalyIndexEstimate:
        """Evaluate IAS as of a specific instant, against a specific
        already-fit TemporalEtasEstimate's expected-count model. There is
        no "current" or "latest" default: the caller names the ETAS fit and
        the evaluation instant explicitly, same as every other service in
        this module.
        """
        etas_source = self.session.get(TemporalEtasEstimate, temporal_etas_estimate_id)
        if etas_source is None:
            raise ValueError(f"temporal ETAS estimate {temporal_etas_estimate_id} not found")
        if etas_source.mu_per_day is None:
            raise ValueError(
                f"temporal ETAS estimate {temporal_etas_estimate_id} did not converge "
                f"(support_state={etas_source.support_state!r}); cannot compute IAS against it"
            )

        completeness_source = self.session.get(
            CompletenessEstimate, etas_source.completeness_estimate_id
        )
        if completeness_source is None or completeness_source.mc_value is None:
            raise ValueError(
                f"temporal ETAS estimate {temporal_etas_estimate_id} references a "
                "completeness estimate with no mc_value"
            )
        if evaluation_end_at <= completeness_source.start_time:
            raise ValueError(
                "evaluation_end_at must be after the completeness estimate's start_time"
            )

        selection = fetch_magnitude_catalog(
            self.session,
            as_of=completeness_source.catalog_as_of,
            start_time=completeness_source.start_time,
            end_time=completeness_source.end_time,
            magnitude_type=completeness_source.magnitude_type,
            min_latitude=completeness_source.min_latitude,
            max_latitude=completeness_source.max_latitude,
            min_longitude=completeness_source.min_longitude,
            max_longitude=completeness_source.max_longitude,
        )
        above_mc = [
            observation
            for observation in selection.observations
            if observation.magnitude >= completeness_source.mc_value
        ]
        event_times_days = [
            (observation.event_time - completeness_source.start_time).total_seconds() / 86400.0
            for observation in above_mc
        ]
        magnitudes = [observation.magnitude for observation in above_mc]
        evaluation_end_days = (
            evaluation_end_at - completeness_source.start_time
        ).total_seconds() / 86400.0

        etas_parameters = EtasParameters(
            mu_per_day=etas_source.mu_per_day,
            k0=etas_source.k0,
            alpha=etas_source.alpha,
            c_days=etas_source.c_days,
            p_exponent=etas_source.p_exponent,
        )
        result = estimate_ias(
            event_times_days,
            magnitudes,
            reference_magnitude=completeness_source.mc_value,
            etas_parameters=etas_parameters,
            evaluation_end_days=evaluation_end_days,
            policy=self.policy,
        )
        component = result.components[0]

        record = SeismicAnomalyIndexEstimate(
            temporal_etas_estimate_id=etas_source.id,
            evaluation_start_time=completeness_source.start_time
            + timedelta(days=result.evaluation_start_days),
            evaluation_end_time=evaluation_end_at,
            evaluation_window_days=self.policy.evaluation_window_days,
            observed_count=component.observed_count,
            expected_count=component.expected_count,
            deviance=component.deviance,
            historical_window_count=result.historical_window_count,
            support_state=result.support_state,
            ias_score=result.ias_score,
            method_version=result.method_version,
            calibration_status=result.calibration_status,
            catalog_as_of=completeness_source.catalog_as_of,
            diagnostics_json=result.diagnostics,
        )
        self.session.add(record)
        self.session.commit()
        return record
