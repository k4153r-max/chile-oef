import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from chile_oef.db.models import (
    CompletenessEstimate,
    EventDeclusteringClassification,
    EventRevision,
    GutenbergRichterEstimate,
    ModifiedOmoriSequenceEstimate,
    SeismicCell,
    SeismicCellBackgroundRate,
    SeismicityBackgroundRateRun,
    SeismicityDeclusteringRun,
    SpatialGrid,
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
from chile_oef.seismicity.gutenberg_richter import estimate_b_value
from chile_oef.seismicity.modified_omori import ModifiedOmoriPolicy, estimate_modified_omori


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
