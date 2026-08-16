import pytest

from chile_oef.tectonics.classification import classify_from_slab
from chile_oef.tectonics.slab2 import SlabSample


def _slab() -> SlabSample:
    return SlabSample(
        depth_km=30.0,
        dip_degrees=20.0,
        strike_degrees=5.0,
        thickness_km=60.0,
        uncertainty_km=1.0,
        interpolation="fixture",
        contributing_nodes=4,
    )


@pytest.mark.parametrize(
    ("depth", "uncertainty", "expected"),
    [(30.0, 1.0, "interface"), (70.0, 1.0, "intraslab"), (5.0, 1.0, "crustal")],
)
def test_rule_baseline_returns_partitioned_uncertainty_mass(
    depth: float,
    uncertainty: float,
    expected: str,
) -> None:
    result = classify_from_slab(
        event_depth_km=depth,
        event_depth_uncertainty_km=uncertainty,
        slab=_slab(),
    )
    assert result.label == expected
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert result.probabilities[expected] > 0.6
    assert result.calibration_status == "uncalibrated_rule_baseline"
    assert result.diagnostics["probabilities_calibrated"] is False
    assert result.diagnostics["chaf_used_as_probability_input"] is False


def test_missing_slab_is_explicitly_unknown() -> None:
    result = classify_from_slab(
        event_depth_km=20.0,
        event_depth_uncertainty_km=None,
        slab=None,
    )
    assert result.label == "unknown"
    assert result.probabilities["unknown"] == 1.0
