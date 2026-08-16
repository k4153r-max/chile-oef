from datetime import datetime

from sqlalchemy.orm import Session

from chile_oef.db.models import CompletenessEstimate
from chile_oef.seismicity.catalog_selection import CatalogSelection, fetch_magnitude_catalog
from chile_oef.seismicity.completeness import (
    CompletenessPolicy,
    estimate_mc_entire_magnitude_range,
    estimate_mc_goodness_of_fit,
    estimate_mc_maximum_curvature,
)


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
