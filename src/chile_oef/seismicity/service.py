import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from chile_oef.db.models import (
    CompletenessEstimate,
    EventDeclusteringClassification,
    GutenbergRichterEstimate,
    SeismicityDeclusteringRun,
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
