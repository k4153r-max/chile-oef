"""Classic CSEP consistency tests (Zechar, Schorlemmer, Liukis, Yu,
Euler, Werner & Jordan 2010; Schorlemmer & Gerstenberger 2007): Number
(N), Magnitude (M), Spatial (S) and joint Likelihood (L) tests. Each asks
whether the observed catalog is a plausible draw from the forecast's
Poisson point process, at a stated significance level.

N-test is evaluated analytically (the sum of independent Poisson
variables is itself Poisson, so no simulation is needed). M/S/L tests
compare the observed joint log-likelihood to a simulated distribution
built by repeatedly drawing synthetic catalogs from the forecast.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.random import Generator
from scipy import stats
from scipy.special import gammaln

from chile_oef.evaluation.scoring import poisson_log_likelihood

_RATE_FLOOR = 1e-12


@dataclass(frozen=True)
class NumberTestResult:
    observed_count: float
    forecast_count: float
    delta1: float
    delta2: float
    consistent_at_alpha: bool
    alpha: float


def number_test(
    observed_counts: Sequence[int], forecast_rates: Sequence[float], *, alpha: float = 0.05
) -> NumberTestResult:
    """CSEP N-test. `delta1 = P(N_sim >= N_obs)`, `delta2 = P(N_sim <= N_obs)`
    under `N_sim ~ Poisson(sum(forecast_rates))`. The forecast is
    inconsistent with the observed total count if either tail probability
    falls below `alpha / 2` (two-sided).
    """
    n_obs = float(np.sum(observed_counts))
    n_pred = float(np.sum(forecast_rates))
    delta1 = float(stats.poisson.sf(n_obs - 1.0, n_pred))
    delta2 = float(stats.poisson.cdf(n_obs, n_pred))
    consistent = delta1 > alpha / 2.0 and delta2 > alpha / 2.0
    return NumberTestResult(n_obs, n_pred, delta1, delta2, consistent, alpha)


@dataclass(frozen=True)
class SimulationTestResult:
    observed_log_likelihood: float
    simulated_log_likelihood_mean: float
    simulated_log_likelihood_p05: float
    simulated_log_likelihood_p95: float
    quantile: float
    consistent_at_alpha: bool
    alpha: float
    n_simulations: int


def _simulated_log_likelihoods(
    rates: np.ndarray, *, rng: Generator, n_simulations: int
) -> np.ndarray:
    simulated_counts = rng.poisson(rates, size=(n_simulations, len(rates)))
    lam = np.clip(rates, _RATE_FLOOR, None)
    log_lam = np.log(lam)
    return np.sum(simulated_counts * log_lam - lam - gammaln(simulated_counts + 1.0), axis=1)


def likelihood_test(
    observed_counts: Sequence[int],
    forecast_rates: Sequence[float],
    *,
    rng: Generator,
    n_simulations: int = 1000,
    alpha: float = 0.05,
) -> SimulationTestResult:
    """CSEP L-test: is the observed joint Poisson log-likelihood under the
    forecast a plausible draw from catalogs simulated from that same
    forecast (full rates, not normalized to the observed total -- N and
    spatial/magnitude effects are both in play here)? One-sided: the
    forecast is inconsistent if the observed log-likelihood falls in the
    unlikely-low tail, `quantile < alpha`.
    """
    rates = np.asarray(forecast_rates, dtype=float)
    observed_ll = poisson_log_likelihood(observed_counts, rates)
    simulated_ll = _simulated_log_likelihoods(rates, rng=rng, n_simulations=n_simulations)
    quantile = float(np.mean(simulated_ll <= observed_ll))
    return SimulationTestResult(
        observed_log_likelihood=observed_ll,
        simulated_log_likelihood_mean=float(np.mean(simulated_ll)),
        simulated_log_likelihood_p05=float(np.percentile(simulated_ll, 5)),
        simulated_log_likelihood_p95=float(np.percentile(simulated_ll, 95)),
        quantile=quantile,
        consistent_at_alpha=quantile >= alpha,
        alpha=alpha,
        n_simulations=n_simulations,
    )


def _normalized_marginal_test(
    observed_marginal_counts: Sequence[int],
    forecast_marginal_rates: Sequence[float],
    *,
    rng: Generator,
    n_simulations: int,
    alpha: float,
) -> SimulationTestResult | None:
    """Shared machinery for the S-test (marginal = per cell, summed over
    magnitude bins) and the M-test (marginal = per magnitude bin, summed
    over cells). Conditioning independent Poisson counts on their known
    sum yields exactly a multinomial distribution over the normalized
    rates, so simulating `multinomial(N_obs, rates / sum(rates))` is the
    exact conditional draw, not an approximation. Scaling those normalized
    rates back up by `N_obs` before scoring makes every simulated (and the
    observed) catalog share the same total, so the ordinary Poisson joint
    log-likelihood scores spatial/magnitude shape only -- the N-test
    signal has been conditioned away. `None` when zero events were
    observed: there is nothing to condition on.
    """
    n_obs = int(round(float(np.sum(observed_marginal_counts))))
    if n_obs == 0:
        return None
    rates = np.asarray(forecast_marginal_rates, dtype=float)
    probabilities = rates / np.sum(rates)
    simulated_counts = rng.multinomial(n_obs, probabilities, size=n_simulations)
    scaled_rates = probabilities * n_obs
    lam = np.clip(scaled_rates, _RATE_FLOOR, None)
    log_lam = np.log(lam)
    simulated_ll = np.sum(
        simulated_counts * log_lam - lam - gammaln(simulated_counts + 1.0), axis=1
    )
    observed_ll = poisson_log_likelihood(observed_marginal_counts, scaled_rates)
    quantile = float(np.mean(simulated_ll <= observed_ll))
    return SimulationTestResult(
        observed_log_likelihood=observed_ll,
        simulated_log_likelihood_mean=float(np.mean(simulated_ll)),
        simulated_log_likelihood_p05=float(np.percentile(simulated_ll, 5)),
        simulated_log_likelihood_p95=float(np.percentile(simulated_ll, 95)),
        quantile=quantile,
        consistent_at_alpha=quantile >= alpha,
        alpha=alpha,
        n_simulations=n_simulations,
    )


def spatial_test(
    observed_counts_per_cell: Sequence[int],
    forecast_rates_per_cell: Sequence[float],
    *,
    rng: Generator,
    n_simulations: int = 1000,
    alpha: float = 0.05,
) -> SimulationTestResult | None:
    """CSEP S-test over the per-cell marginal (already summed across
    magnitude bins by the caller)."""
    return _normalized_marginal_test(
        observed_counts_per_cell,
        forecast_rates_per_cell,
        rng=rng,
        n_simulations=n_simulations,
        alpha=alpha,
    )


def magnitude_test(
    observed_counts_per_magnitude_bin: Sequence[int],
    forecast_rates_per_magnitude_bin: Sequence[float],
    *,
    rng: Generator,
    n_simulations: int = 1000,
    alpha: float = 0.05,
) -> SimulationTestResult | None:
    """CSEP M-test over the per-magnitude-bin marginal (already summed
    across cells by the caller)."""
    return _normalized_marginal_test(
        observed_counts_per_magnitude_bin,
        forecast_rates_per_magnitude_bin,
        rng=rng,
        n_simulations=n_simulations,
        alpha=alpha,
    )
