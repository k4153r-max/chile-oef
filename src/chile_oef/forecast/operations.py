from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from chile_oef.db.models import (
    ForecastRun,
    GutenbergRichterEstimate,
    SeismicityBackgroundRateRun,
    SeismicityDeclusteringRun,
    SpatiotemporalEtasEstimate,
)
from chile_oef.forecast.service import ForecastService
from chile_oef.forecast.simulation import CatalogSimulationPolicy
from chile_oef.forecast.specification import ForecastSpecification


@dataclass(frozen=True)
class ForecastFreshness:
    state: str
    age_seconds: float | None
    valid_now: bool
    expected_issue_interval_seconds: float


@dataclass(frozen=True)
class OperationalIssuanceResult:
    run: ForecastRun
    created: bool


def assess_forecast_freshness(
    run: ForecastRun | None,
    *,
    as_of: datetime,
    expected_issue_interval: timedelta = timedelta(hours=1),
) -> ForecastFreshness:
    """Classify the latest forecast without pretending stale output is current."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    interval_seconds = expected_issue_interval.total_seconds()
    if interval_seconds <= 0:
        raise ValueError("expected_issue_interval must be positive")
    if run is None:
        return ForecastFreshness(
            state="missing",
            age_seconds=None,
            valid_now=False,
            expected_issue_interval_seconds=interval_seconds,
        )

    age_seconds = (as_of - run.issued_at).total_seconds()
    valid_now = run.validity_start <= as_of < run.validity_end
    if age_seconds < 0:
        state = "future_issuance"
    elif not valid_now:
        state = "expired"
    elif age_seconds > 2.0 * interval_seconds:
        state = "stale"
    else:
        state = "fresh"
    return ForecastFreshness(
        state=state,
        age_seconds=age_seconds,
        valid_now=valid_now,
        expected_issue_interval_seconds=interval_seconds,
    )


def issue_operational_forecast(
    session: Session,
    *,
    specification: ForecastSpecification,
    issued_at: datetime,
    horizon_id: str,
    simulation_policy: CatalogSimulationPolicy | None = None,
) -> OperationalIssuanceResult:
    """Issue one idempotent scheduled forecast from the latest compatible lineage.

    A PostgreSQL advisory transaction lock serializes the exact scheduled slot.
    The function reuses an existing run for that slot and never updates it.
    """
    if issued_at.tzinfo is None:
        raise ValueError("issued_at must be timezone-aware")
    lock_key = f"chile-oef:forecast:{horizon_id}:{issued_at.isoformat()}"
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock_key})

    existing = session.scalar(
        select(ForecastRun).where(
            ForecastRun.issued_at == issued_at,
            ForecastRun.horizon_id == horizon_id,
            ForecastRun.trigger_type == "scheduled",
        )
    )
    if existing is not None:
        return OperationalIssuanceResult(run=existing, created=False)

    etas = session.scalar(
        select(SpatiotemporalEtasEstimate)
        .where(SpatiotemporalEtasEstimate.converged.is_(True))
        .order_by(SpatiotemporalEtasEstimate.created_at.desc())
        .limit(1)
    )
    if etas is None:
        raise ValueError("no converged spatiotemporal ETAS estimate is available")
    gr = session.scalar(
        select(GutenbergRichterEstimate)
        .where(
            GutenbergRichterEstimate.completeness_estimate_id == etas.completeness_estimate_id,
            GutenbergRichterEstimate.b_value.is_not(None),
        )
        .order_by(GutenbergRichterEstimate.created_at.desc())
        .limit(1)
    )
    if gr is None:
        raise ValueError("latest ETAS estimate has no compatible Gutenberg-Richter estimate")

    background = session.scalar(
        select(SeismicityBackgroundRateRun)
        .join(
            SeismicityDeclusteringRun,
            SeismicityDeclusteringRun.id == SeismicityBackgroundRateRun.declustering_run_id,
        )
        .where(
            SeismicityDeclusteringRun.gutenberg_richter_estimate_id == gr.id,
            SeismicityBackgroundRateRun.grid_id == specification.grid_id,
        )
        .order_by(SeismicityBackgroundRateRun.created_at.desc())
        .limit(1)
    )

    run = ForecastService(
        session,
        specification=specification,
        simulation_policy=simulation_policy or CatalogSimulationPolicy(),
    ).issue_forecast(
        spatiotemporal_etas_estimate_id=etas.id,
        gutenberg_richter_estimate_id=gr.id,
        background_rate_run_id=background.id if background is not None else None,
        issued_at=issued_at,
        horizon_id=horizon_id,
        trigger_type="scheduled",
    )
    return OperationalIssuanceResult(run=run, created=True)
