import numpy as np
import pytest
from scipy import stats

from chile_oef.evaluation.csep_tests import (
    likelihood_test,
    magnitude_test,
    number_test,
    spatial_test,
)


def test_number_test_deltas_match_direct_monte_carlo() -> None:
    """Independent re-derivation: draw N_sim directly from Poisson(forecast
    total) via numpy (not via number_test's own scipy.stats.poisson call
    path) and check the empirical tail fractions match delta1/delta2.
    """
    forecast_rates = [2.0, 3.0]
    observed_counts = [2, 3]
    result = number_test(observed_counts, forecast_rates, alpha=0.05)
    rng = np.random.default_rng(1)
    simulated = rng.poisson(sum(forecast_rates), size=200_000)
    empirical_delta1 = float(np.mean(simulated >= result.observed_count))
    empirical_delta2 = float(np.mean(simulated <= result.observed_count))
    assert result.delta1 == pytest.approx(empirical_delta1, abs=0.01)
    assert result.delta2 == pytest.approx(empirical_delta2, abs=0.01)


def test_number_test_matched_totals_are_consistent() -> None:
    result = number_test([5], [5.0], alpha=0.05)
    assert result.consistent_at_alpha is True


def test_number_test_extreme_mismatch_is_inconsistent() -> None:
    result = number_test([50], [5.0], alpha=0.05)
    assert result.consistent_at_alpha is False
    assert result.delta1 < 0.001


def test_likelihood_test_quantile_is_uniform_under_the_null() -> None:
    """If the observed catalog really is drawn from the forecast (the null
    hypothesis the L-test assumes), the reported quantile is a probability
    integral transform and must be uniformly distributed on [0, 1] --
    independent of anything in likelihood_test's own implementation. A mean
    far from 0.5, or a lopsided fraction below/above 0.5, would mean the
    test statistic is biased.
    """
    rates = np.array([1.5, 0.3, 2.0, 0.8, 1.1])
    quantiles = []
    for seed in range(250):
        observed = np.random.default_rng(10_000 + seed).poisson(rates)
        result = likelihood_test(
            observed, rates, rng=np.random.default_rng(seed), n_simulations=400
        )
        quantiles.append(result.quantile)
    quantiles_arr = np.array(quantiles)
    assert quantiles_arr.mean() == pytest.approx(0.5, abs=0.08)
    assert np.mean(quantiles_arr < 0.5) == pytest.approx(0.5, abs=0.12)


def test_likelihood_test_detects_a_grossly_wrong_forecast() -> None:
    rates = np.array([0.01, 0.01, 0.01])
    observed = np.array([50, 50, 50])
    result = likelihood_test(observed, rates, rng=np.random.default_rng(0), n_simulations=1000)
    assert result.consistent_at_alpha is False
    assert result.quantile < 0.01


def test_multinomial_conditioning_matches_independent_rejection_sampling() -> None:
    """The S/M-test machinery asserts that conditioning independent Poisson
    counts on their known sum gives exactly a multinomial distribution.
    Verify that by brute-force rejection sampling from independent
    Poissons -- a completely different sampling method -- and comparing
    per-cell means against numpy's multinomial sampler.
    """
    rng = np.random.default_rng(7)
    rates = np.array([0.5, 1.0, 1.5])
    n_obs = 3
    accepted = []
    while len(accepted) < 20_000:
        draw = rng.poisson(rates)
        if draw.sum() == n_obs:
            accepted.append(draw)
    rejection_mean = np.mean(accepted, axis=0)
    multinomial_mean = rng.multinomial(n_obs, rates / rates.sum(), size=20_000).mean(axis=0)
    assert np.allclose(rejection_mean, multinomial_mean, atol=0.05)


def test_spatial_test_quantile_is_uniform_under_the_null() -> None:
    rates = np.array([1.5, 0.3, 2.0, 0.8, 1.1, 0.4])
    quantiles = []
    for seed in range(250):
        observed = np.random.default_rng(20_000 + seed).poisson(rates)
        result = spatial_test(observed, rates, rng=np.random.default_rng(seed), n_simulations=400)
        if result is None:
            # A genuine, rare null draw with zero total observed events
            # (P(sum(Poisson(rates)) == 0) = exp(-sum(rates)) =~ 0.2% here)
            # -- correctly not_estimable, not a failure of this check.
            continue
        quantiles.append(result.quantile)
    quantiles_arr = np.array(quantiles)
    assert len(quantiles_arr) > 200
    assert quantiles_arr.mean() == pytest.approx(0.5, abs=0.08)


def test_spatial_test_detects_a_spatial_mismatch() -> None:
    forecast_rates = [10.0, 0.1, 0.1]
    observed_counts = [0, 5, 5]
    result = spatial_test(
        observed_counts, forecast_rates, rng=np.random.default_rng(0), n_simulations=2000
    )
    assert result is not None
    assert result.consistent_at_alpha is False
    assert result.quantile < 0.01


def test_spatial_test_returns_none_when_zero_events_observed() -> None:
    assert spatial_test([0, 0, 0], [1.0, 2.0, 3.0], rng=np.random.default_rng(0)) is None


def test_magnitude_test_detects_a_magnitude_distribution_mismatch() -> None:
    forecast_rates_per_bin = [10.0, 1.0, 0.1]
    observed_counts_per_bin = [0, 0, 20]
    result = magnitude_test(
        observed_counts_per_bin,
        forecast_rates_per_bin,
        rng=np.random.default_rng(0),
        n_simulations=2000,
    )
    assert result is not None
    assert result.consistent_at_alpha is False


def test_magnitude_test_returns_none_when_zero_events_observed() -> None:
    assert magnitude_test([0, 0], [1.0, 2.0], rng=np.random.default_rng(0)) is None


def test_poisson_sf_and_cdf_are_complementary_sanity_check() -> None:
    """A pinned-down sanity check on the scipy call convention itself
    (off-by-one errors in discrete tail probabilities are easy to make):
    P(N >= k) computed via sf(k - 1, mu) must equal 1 - cdf(k - 1, mu).
    """
    mu = 7.3
    k = 5
    assert stats.poisson.sf(k - 1, mu) == pytest.approx(1.0 - stats.poisson.cdf(k - 1, mu))
