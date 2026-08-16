import random

import numpy as np
import pytest
from scipy.stats import norm

from chile_oef.seismicity.completeness import (
    CompletenessPolicy,
    estimate_mc_entire_magnitude_range,
    estimate_mc_goodness_of_fit,
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


def _exact_gr_catalog_with_underdetected_tail(
    *, mc_true: float, b_value: float, n0: int, bin_width: float, top_magnitude: float
) -> list[float]:
    """Deterministic (no RNG) synthetic catalog: exact integer Gutenberg-Richter
    counts at and above ``mc_true``, plus a deliberately flat, far-below-trend
    tail beneath it simulating under-detection. Because the counts above
    ``mc_true`` are constructed to be *exactly* what a GR line predicts (up to
    integer rounding), Goodness-of-Fit should reconstruct that line almost
    perfectly once it reaches ``mc_true`` -- this is a golden-value fixture,
    not a statistical recovery claim.
    """
    bin_count = round((top_magnitude - mc_true) / bin_width) + 1
    bins = [round(mc_true + index * bin_width, 10) for index in range(bin_count)]
    cumulative = {
        bin_value: round(n0 * 10 ** (-b_value * (bin_value - mc_true))) for bin_value in bins
    }
    noncumulative = {
        bin_value: (
            cumulative[bin_value] - cumulative[bins[index + 1]]
            if index + 1 < len(bins)
            else cumulative[bin_value]
        )
        for index, bin_value in enumerate(bins)
    }
    below_bins = [round(mc_true - index * bin_width, 10) for index in range(1, 11)]
    for bin_value in below_bins:
        noncumulative[bin_value] = 5
    magnitudes: list[float] = []
    for bin_value, count in noncumulative.items():
        magnitudes.extend([bin_value] * count)
    return magnitudes


def test_goodness_of_fit_regression_fixture_recovers_exact_gr_break() -> None:
    magnitudes = _exact_gr_catalog_with_underdetected_tail(
        mc_true=3.0, b_value=1.0, n0=1000, bin_width=0.1, top_magnitude=5.0
    )
    result = estimate_mc_goodness_of_fit(magnitudes)
    assert result.event_count == len(magnitudes)
    assert result.support_state == "supported"
    assert result.mc_value == pytest.approx(3.0)
    assert result.achieved_confidence_percent == pytest.approx(95.0)
    assert result.best_fit_quality_percent == pytest.approx(99.62, abs=0.05)
    assert result.role == "diagnostic"


def test_goodness_of_fit_refuses_rather_than_guess_on_pure_noise() -> None:
    """Uniform-random magnitudes carry no Gutenberg-Richter structure at all.
    The estimator must not silently return whichever candidate happened to
    score highest -- it should report that no candidate reached even the
    fallback confidence level.
    """
    rng = random.Random(1)
    magnitudes = [round(rng.uniform(2.0, 6.0), 1) for _ in range(500)]
    result = estimate_mc_goodness_of_fit(magnitudes)
    assert result.mc_value is None
    assert result.achieved_confidence_percent is None
    assert (
        result.diagnostics["reason"] == "fallback_confidence_threshold_not_reached_at_any_candidate"
    )
    assert result.best_fit_quality_percent is not None
    assert result.best_fit_quality_percent < result.diagnostics["fallback_confidence_percent"]


def test_goodness_of_fit_below_minimum_sample_is_not_estimable() -> None:
    result = estimate_mc_goodness_of_fit([3.0] * 49)
    assert result.support_state == "not_estimable"
    assert result.mc_value is None
    assert result.achieved_confidence_percent is None
    assert result.best_fit_quality_percent is None


def _synthetic_normal_rolloff_catalog(
    *,
    seed: int,
    sample_size: int,
    true_mu: float,
    true_sigma: float,
    true_b: float,
) -> list[float]:
    """Rejection-sample the exact generative model Entire Magnitude Range
    assumes: a Gutenberg-Richter rate thinned by a normal-CDF detection
    function. Unlike the logistic-rolloff fixture used for Maximum
    Curvature, this is a correctly-specified-model test: EMR should recover
    all three parameters closely, not just land in the right neighborhood.
    """
    rng = np.random.default_rng(seed)
    beta = true_b * np.log(10.0)
    floor, cap = true_mu - 1.5, true_mu + 3.0

    def gr_density(magnitude: np.ndarray) -> np.ndarray:
        return beta * np.exp(-beta * (magnitude - floor))

    def detection_probability(magnitude: np.ndarray) -> np.ndarray:
        return norm.cdf((magnitude - true_mu) / true_sigma)

    envelope = gr_density(np.array([floor]))[0]
    accepted: list[float] = []
    while len(accepted) < sample_size:
        batch = rng.uniform(floor, cap, size=4000)
        acceptance = gr_density(batch) * detection_probability(batch) / envelope
        draws = rng.uniform(0.0, 1.0, size=4000)
        accepted.extend(batch[draws < acceptance].tolist())
    return accepted[:sample_size]


def test_entire_magnitude_range_below_minimum_sample_is_not_estimable() -> None:
    result = estimate_mc_entire_magnitude_range([3.0] * 49)
    assert result.support_state == "not_estimable"
    assert result.mc_value is None
    assert result.converged is False
    assert result.bootstrap_resamples_converged == 0
    assert result.role == "primary"


def test_entire_magnitude_range_recovers_synthetic_parameters() -> None:
    """Correctly-specified-model recovery check, seeded and deterministic.
    Tolerances are loose enough to absorb Monte Carlo noise from the
    rejection sampler and a small bootstrap count, not to hide a wrong
    estimator.
    """
    true_mu, true_sigma, true_b = 3.0, 0.12, 1.0
    magnitudes = _synthetic_normal_rolloff_catalog(
        seed=7, sample_size=1500, true_mu=true_mu, true_sigma=true_sigma, true_b=true_b
    )
    policy = CompletenessPolicy(emr_bootstrap_resamples=30)
    result = estimate_mc_entire_magnitude_range(magnitudes, policy=policy)

    assert result.converged is True
    assert result.role == "primary"
    assert result.calibration_status == "uncalibrated_primary_estimator"
    assert result.mc_value == pytest.approx(true_mu, abs=0.15)
    assert result.detection_sigma_magnitude == pytest.approx(true_sigma, abs=0.1)
    assert result.b_value == pytest.approx(true_b, abs=0.3)
    assert result.bootstrap_resamples_converged >= 20
    assert result.mc_confidence_interval is not None
    lower, upper = result.mc_confidence_interval
    assert lower < true_mu < upper
