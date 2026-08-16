import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from chile_oef.db.models import CompletenessEstimate, GutenbergRichterEstimate
from chile_oef.seismicity.catalog_selection import CatalogSelection, fetch_magnitude_catalog
from chile_oef.seismicity.completeness import (
    CompletenessPolicy,
    estimate_mc_entire_magnitude_range,
    estimate_mc_goodness_of_fit,
    estimate_mc_maximum_curvature,
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
