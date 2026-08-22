import uuid
from datetime import UTC, datetime, timedelta

import pytest

from chile_oef.db.models import ForecastRun
from chile_oef.forecast.operations import assess_forecast_freshness


def _run(*, issued_at: datetime, validity_end: datetime) -> ForecastRun:
    return ForecastRun(
        id=uuid.uuid4(),
        spatiotemporal_etas_estimate_id=uuid.uuid4(),
        gutenberg_richter_estimate_id=uuid.uuid4(),
        grid_id="grid",
        trigger_type="scheduled",
        issued_at=issued_at,
        validity_start=issued_at,
        validity_end=validity_end,
        horizon_id="P7D",
        reference_magnitude=5.0,
        b_value_used=1.0,
        region_area_km2=1.0,
        input_catalog_as_of=issued_at,
        method_version="fixture",
        calibration_status="fixture",
        cell_count=1,
        magnitude_bin_count=1,
        diagnostics_json={},
    )


def test_forecast_freshness_states() -> None:
    now = datetime(2026, 8, 22, 12, tzinfo=UTC)
    fresh = _run(issued_at=now - timedelta(minutes=30), validity_end=now + timedelta(days=1))
    stale = _run(issued_at=now - timedelta(hours=3), validity_end=now + timedelta(days=1))
    expired = _run(issued_at=now - timedelta(days=8), validity_end=now - timedelta(days=1))

    assert assess_forecast_freshness(fresh, as_of=now).state == "fresh"
    assert assess_forecast_freshness(stale, as_of=now).state == "stale"
    assert assess_forecast_freshness(expired, as_of=now).state == "expired"
    assert assess_forecast_freshness(None, as_of=now).state == "missing"


def test_forecast_freshness_requires_aware_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        assess_forecast_freshness(None, as_of=datetime(2026, 8, 22))
