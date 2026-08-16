from datetime import datetime

from sqlalchemy.orm import Session

from chile_oef.db.models import CompletenessEstimate
from chile_oef.seismicity.catalog_selection import fetch_magnitude_catalog
from chile_oef.seismicity.completeness import CompletenessPolicy, estimate_mc_maximum_curvature


class CompletenessEstimationService:
    def __init__(self, session: Session, *, policy: CompletenessPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or CompletenessPolicy()

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
        selection = fetch_magnitude_catalog(
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
