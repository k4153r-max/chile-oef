import random

import pytest

from chile_oef.seismicity.completeness import (
    CompletenessPolicy,
    estimate_mc_maximum_curvature,
    support_state,
)


@pytest.mark.parametrize(
    ("event_count", "expected"),
    [
        (0, "not_estimable"),
        (49, "not_estimable"),
        (50, "research_only"),
        (99, "research_only"),
        (100, "high_uncertainty"),
        (199, "high_uncertainty"),
        (200, "supported"),
        (10_000, "supported"),
    ],
)
def test_support_state_matches_completeness_policy_bands(event_count: int, expected: str) -> None:
    assert support_state(event_count) == expected


def test_support_state_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="event_count"):
        support_state(-1)


def test_below_minimum_sample_is_not_estimable_without_computing_mc() -> None:
    magnitudes = [3.0] * 49
    result = estimate_mc_maximum_curvature(magnitudes)
    assert result.support_state == "not_estimable"
    assert result.mc_value is None
    assert result.raw_peak_bin_magnitude is None
    assert result.event_count == 49
    assert result.role == "diagnostic"


def test_maximum_curvature_regression_fixture() -> None:
    """Fixed literal catalog: pins the exact histogram peak and correction.

    2.0-2.9 events are progressively thinned (simulating under-detection
    below completeness) while 3.0 has the most events of any bin, so the
    raw mode is unambiguous and this fixture is a pure golden-value check,
    independent of any statistical recovery claim.
    """
    magnitudes = (
        [2.0] * 5
        + [2.1] * 8
        + [2.2] * 12
        + [2.3] * 18
        + [2.4] * 25
        + [2.5] * 34
        + [2.6] * 44
        + [2.7] * 55
        + [2.8] * 67
        + [2.9] * 80
        + [3.0] * 95
        + [3.1] * 70
        + [3.2] * 52
        + [3.3] * 38
        + [3.4] * 28
        + [3.5] * 21
    )
    policy = CompletenessPolicy()
    result = estimate_mc_maximum_curvature(magnitudes, policy=policy)
    assert result.event_count == len(magnitudes)
    assert result.support_state == "supported"
    assert result.raw_peak_bin_magnitude == pytest.approx(3.0)
    assert result.mc_value == pytest.approx(3.0 + policy.maximum_curvature_correction_magnitude)
    assert result.diagnostics["raw_peak_bin_event_count"] == 95
    assert result.calibration_status == "uncalibrated_diagnostic_estimator"


def test_correction_is_applied_exactly_as_configured() -> None:
    """The correction offset is a documented policy constant, not a fitted
    quantity: this must hold for any policy value, exactly.
    """
    magnitudes = [4.2] * 250
    for correction in (0.0, 0.1, 0.2, 0.35):
        policy = CompletenessPolicy(maximum_curvature_correction_magnitude=correction)
        result = estimate_mc_maximum_curvature(magnitudes, policy=policy)
        assert result.raw_peak_bin_magnitude == pytest.approx(4.2)
        assert result.mc_value == pytest.approx(4.2 + correction)


def _synthetic_thinned_catalog(
    *,
    true_mc: float,
    b_value: float,
    floor: float,
    cap: float,
    rolloff_scale: float,
    sample_size: int,
    seed: int,
) -> list[float]:
    """Rejection-sample a Gutenberg-Richter density thinned by a logistic
    detection function centered at ``true_mc``. The product of a decreasing
    GR density and an increasing detection probability has an interior mode
    near the true completeness magnitude, which is the textbook basis for
    maximum-curvature estimators (Wiemer & Wyss, 2000; Woessner & Wiemer,
    2005) and is used here only to sanity-check recovery direction and
    order of magnitude, not to assert estimator precision.
    """
    rng = random.Random(seed)
    beta = b_value * 2.302585092994046  # b * ln(10)

    def gr_density(magnitude: float) -> float:
        return beta * (2.718281828459045 ** (-beta * (magnitude - floor)))

    def detection_probability(magnitude: float) -> float:
        return 1.0 / (1.0 + 2.718281828459045 ** (-(magnitude - true_mc) / rolloff_scale))

    envelope = gr_density(floor)
    accepted: list[float] = []
    while len(accepted) < sample_size:
        candidate = rng.uniform(floor, cap)
        acceptance = gr_density(candidate) * detection_probability(candidate) / envelope
        if rng.random() < acceptance:
            accepted.append(candidate)
    return accepted


def test_maximum_curvature_recovers_synthetic_completeness_within_a_loose_band() -> None:
    true_mc = 3.0
    magnitudes = _synthetic_thinned_catalog(
        true_mc=true_mc,
        b_value=1.0,
        floor=true_mc - 1.5,
        cap=true_mc + 3.0,
        rolloff_scale=0.15,
        sample_size=4000,
        seed=20260816,
    )
    result = estimate_mc_maximum_curvature(magnitudes)
    assert result.support_state == "supported"
    assert result.mc_value is not None
    # Loose, seeded, deterministic bound: a smooth logistic rolloff (rather
    # than a hard detection cutoff) shifts the density mode a few hundredths
    # above true_mc even before the +0.2 literature correction is added, so
    # this only checks the estimator lands in the right neighborhood on a
    # known synthetic catalog -- it is not a precision claim. completeness.md
    # already documents MaxC as diagnostic-only pending a registered
    # simulation study.
    assert result.mc_value == pytest.approx(true_mc, abs=0.5)
