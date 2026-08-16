from datetime import UTC, datetime

import pytest

from chile_oef.seismicity.catalog_selection import (
    MagnitudeObservation,
    fetch_magnitude_catalog,
    select_single_magnitude_type,
)


def _observation(magnitude: float, magnitude_type: str) -> MagnitudeObservation:
    return MagnitudeObservation(
        event_time=datetime(2026, 1, 1, tzinfo=UTC),
        magnitude=magnitude,
        magnitude_type=magnitude_type,
    )


def test_select_single_magnitude_type_drops_mixed_scales() -> None:
    observations = [
        _observation(4.1, "ml"),
        _observation(4.5, "mw"),
        _observation(3.9, "ml"),
    ]
    selected = select_single_magnitude_type(observations, "ml")
    assert [o.magnitude for o in selected] == [4.1, 3.9]


def test_select_single_magnitude_type_empty_when_no_match() -> None:
    observations = [_observation(4.1, "ml")]
    assert select_single_magnitude_type(observations, "mw") == []


def test_fetch_magnitude_catalog_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        fetch_magnitude_catalog(
            session=None,  # type: ignore[arg-type]
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            start_time=datetime(2025, 1, 1),
            end_time=datetime(2026, 1, 1, tzinfo=UTC),
            magnitude_type="mw",
        )


def test_fetch_magnitude_catalog_rejects_inverted_window() -> None:
    with pytest.raises(ValueError, match="start_time must be before end_time"):
        fetch_magnitude_catalog(
            session=None,  # type: ignore[arg-type]
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2025, 1, 1, tzinfo=UTC),
            magnitude_type="mw",
        )
