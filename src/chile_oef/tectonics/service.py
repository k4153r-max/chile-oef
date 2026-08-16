import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from chile_oef.db.models import (
    EventRevision,
    EventTectonicClassification,
    TectonicRelease,
)
from chile_oef.tectonics.classification import (
    ClassificationParameters,
    classify_from_slab,
)
from chile_oef.tectonics.faults import FaultRepository
from chile_oef.tectonics.slab2 import SlabRepository


class EventClassificationService:
    def __init__(
        self,
        session: Session,
        *,
        slab_release: TectonicRelease,
        fault_release: TectonicRelease | None = None,
        parameters: ClassificationParameters | None = None,
    ) -> None:
        if slab_release.status != "ready":
            raise ValueError("slab release is not ready")
        if slab_release.source_id != "slab2_south_america_2018":
            raise ValueError("slab release has the wrong source")
        if fault_release is not None and fault_release.status != "ready":
            raise ValueError("fault release is not ready")
        if fault_release is not None and fault_release.source_id != "chaf_2020":
            raise ValueError("fault release has the wrong source")
        self.session = session
        self.slab_release = slab_release
        self.fault_release = fault_release
        self.parameters = parameters or ClassificationParameters()
        resolution = float(slab_release.metadata_json.get("resolution_degrees", 0.05))
        self.slab_repository = SlabRepository(
            session,
            slab_release.id,
            resolution=resolution,
        )
        self.fault_repository = (
            FaultRepository(session, fault_release.id) if fault_release else None
        )

    def classify_revision(
        self,
        revision: EventRevision,
    ) -> EventTectonicClassification:
        fault_release_id = self.fault_release.id if self.fault_release else None
        fault_release_condition = (
            EventTectonicClassification.fault_release_id == fault_release_id
            if fault_release_id is not None
            else EventTectonicClassification.fault_release_id.is_(None)
        )
        existing = self.session.scalar(
            select(EventTectonicClassification).where(
                EventTectonicClassification.event_revision_id == revision.id,
                EventTectonicClassification.slab_release_id == self.slab_release.id,
                fault_release_condition,
                EventTectonicClassification.method_version == self.parameters.method_version,
            )
        )
        if existing is not None:
            return existing
        slab = self.slab_repository.sample(
            latitude=revision.latitude,
            longitude=revision.longitude,
        )
        result = classify_from_slab(
            event_depth_km=revision.depth_km,
            event_depth_uncertainty_km=revision.depth_uncertainty_km,
            slab=slab,
            parameters=self.parameters,
        )
        nearest_fault = (
            self.fault_repository.nearest(
                latitude=revision.latitude,
                longitude=revision.longitude,
            )
            if self.fault_repository
            else None
        )
        diagnostics = {
            **result.diagnostics,
            "slab_interpolation": slab.interpolation if slab else None,
            "slab_contributing_nodes": slab.contributing_nodes if slab else 0,
            "nearest_fault_trace_id": (str(nearest_fault.trace_id) if nearest_fault else None),
            "nearest_fault_external_id": (nearest_fault.external_id if nearest_fault else None),
            "nearest_fault_activity_class": (
                nearest_fault.activity_class if nearest_fault else None
            ),
            "fault_distance_interpretation": "horizontal_distance_to_surface_trace",
        }
        classification = EventTectonicClassification(
            event_revision_id=revision.id,
            slab_release_id=self.slab_release.id,
            fault_release_id=fault_release_id,
            method_version=result.method_version,
            calibration_status=result.calibration_status,
            label=result.label,
            max_probability=max(result.probabilities.values()),
            slab_depth_km=result.slab_depth_km,
            signed_vertical_residual_km=result.signed_vertical_residual_km,
            signed_normal_distance_km=result.signed_normal_distance_km,
            horizontal_fault_distance_km=(nearest_fault.distance_km if nearest_fault else None),
            probabilities_json=result.probabilities,
            diagnostics_json=diagnostics,
        )
        self.session.add(classification)
        self.session.commit()
        return classification

    def classify_pending(self, *, limit: int = 1000) -> int:
        fault_release_id = self.fault_release.id if self.fault_release else None
        fault_release_condition = (
            EventTectonicClassification.fault_release_id == fault_release_id
            if fault_release_id is not None
            else EventTectonicClassification.fault_release_id.is_(None)
        )
        already_classified = select(EventTectonicClassification.event_revision_id).where(
            EventTectonicClassification.slab_release_id == self.slab_release.id,
            fault_release_condition,
            EventTectonicClassification.method_version == self.parameters.method_version,
        )
        revisions = list(
            self.session.scalars(
                select(EventRevision)
                .where(EventRevision.id.not_in(already_classified))
                .order_by(EventRevision.available_at)
                .limit(limit)
            )
        )
        for revision in revisions:
            self.classify_revision(revision)
        return len(revisions)


def ready_release(session: Session, source_id: str) -> TectonicRelease:
    releases = list(
        session.scalars(
            select(TectonicRelease)
            .where(
                TectonicRelease.source_id == source_id,
                TectonicRelease.status == "ready",
            )
            .order_by(TectonicRelease.recorded_at.desc())
        )
    )
    if len(releases) != 1:
        raise ValueError(f"expected one ready release for {source_id!r}, found {len(releases)}")
    return releases[0]


def classification_by_revision(
    session: Session,
    revision_id: uuid.UUID,
) -> list[EventTectonicClassification]:
    return list(
        session.scalars(
            select(EventTectonicClassification)
            .where(EventTectonicClassification.event_revision_id == revision_id)
            .order_by(EventTectonicClassification.created_at.desc())
        )
    )
