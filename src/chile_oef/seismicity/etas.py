import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import optimize

from chile_oef.seismicity.modified_omori import _integral_rate


@dataclass(frozen=True)
class EtasPolicy:
    version: int = 1
    status: str = "experimental"
    method_version: str = "temporal_etas_mle_v1"
    calibration_status: str = "uncalibrated_mle_estimator"
    minimum_events: int = 100
    mu_bounds_per_day: tuple[float, float] = (1e-6, 50.0)
    k0_bounds: tuple[float, float] = (1e-6, 100.0)
    alpha_bounds: tuple[float, float] = (0.0, 5.0)
    c_bounds_days: tuple[float, float] = (1e-4, 10.0)
    p_bounds: tuple[float, float] = (0.3, 3.0)
    restarts: int = 6
    restart_seed: int = 20260816


@dataclass(frozen=True)
class EtasParameters:
    mu_per_day: float
    k0: float
    alpha: float
    c_days: float
    p_exponent: float


@dataclass(frozen=True)
class EtasEstimate:
    event_count: int
    support_state: str
    observation_duration_days: float
    reference_magnitude: float
    parameters: EtasParameters | None
    converged: bool
    log_likelihood: float | None
    restarts_converged: int
    method_version: str
    calibration_status: str
    diagnostics: dict[str, Any]


def _conditional_intensities(
    t: np.ndarray, m: np.ndarray, mc: float, mu: float, k0: float, alpha: float, c: float, p: float
) -> np.ndarray:
    """lambda(t_i) for every event i, from every strictly earlier event j
    (the full ETAS self-exciting sum, O(n^2) -- no hard parent assignment,
    unlike Modified Omori's per-family fit: every earlier event contributes
    to every later event's rate, weighted by its own magnitude and the
    triggering kernel).
    """
    dt = t[:, None] - t[None, :]
    mask = dt > 0.0
    productivity = k0 * np.exp(alpha * (m - mc))
    kernel = np.where(mask, 1.0 / np.power(np.where(mask, dt + c, 1.0), p), 0.0)
    contributions = kernel * productivity[None, :]
    return mu + contributions.sum(axis=1)


def _integral_of_intensity(
    t: np.ndarray,
    m: np.ndarray,
    mc: float,
    mu: float,
    k0: float,
    alpha: float,
    c: float,
    p: float,
    duration_days: float,
) -> float:
    """Integral of lambda(t) over [0, duration_days] -- the background term
    plus, for each event, its full triggering contribution integrated from
    its own occurrence time to the end of the window.
    """
    remaining = duration_days - t
    remaining = np.clip(remaining, 0.0, None)
    productivity = k0 * np.exp(alpha * (m - mc))
    per_event_integral = np.array([_integral_rate(c, p, d) for d in remaining])
    return mu * duration_days + float(np.sum(productivity * per_event_integral))


def _negative_log_likelihood(
    params: np.ndarray, t: np.ndarray, m: np.ndarray, mc: float, duration_days: float
) -> float:
    mu, k0, alpha, c, p = params
    if mu <= 0 or k0 < 0 or c <= 0:
        return math.inf
    intensities = _conditional_intensities(t, m, mc, mu, k0, alpha, c, p)
    if np.any(intensities <= 0) or not np.all(np.isfinite(intensities)):
        return math.inf
    integral = _integral_of_intensity(t, m, mc, mu, k0, alpha, c, p, duration_days)
    if integral <= 0 or not math.isfinite(integral):
        return math.inf
    log_likelihood = float(np.sum(np.log(intensities))) - integral
    if not math.isfinite(log_likelihood):
        return math.inf
    return -log_likelihood


def estimate_temporal_etas(
    event_times_days: Sequence[float],
    event_magnitudes: Sequence[float],
    *,
    reference_magnitude: float,
    observation_duration_days: float,
    policy: EtasPolicy | None = None,
    initial_guess: EtasParameters | None = None,
) -> EtasEstimate:
    """Temporal ETAS (Ogata, 1988) maximum-likelihood fit:

        lambda(t) = mu + sum_{t_j < t} k0 * exp(alpha*(m_j - mc)) / (t - t_j + c)^p

    Unlike Modified Omori, this is fit jointly over the *entire* catalog at
    once -- no hard parent/family assignment from declustering is used or
    needed; every earlier event contributes to every later event's rate.
    ``reference_magnitude`` (mc) anchors the magnitude-productivity scaling
    and should be a declared, already-estimated Mc (Entire Magnitude Range),
    not re-derived here, per the same discipline as Gutenberg-Richter and
    declustering.

    A 5-parameter joint optimization with an O(n^2) likelihood is
    materially harder to fit reliably than Modified Omori's 2-parameter
    per-family fit: it is fit with several restarts from different initial
    points (the default seeded from Modified Omori-style (c, p) plus a
    background-rate-style mu, when `initial_guess` is not supplied) and the
    best (highest-likelihood) converged result is kept, with the number of
    restarts that converged recorded in diagnostics.
    """
    policy = policy or EtasPolicy()
    event_count = len(event_times_days)
    diagnostics: dict[str, Any] = {
        "estimator": "temporal_etas_mle",
        "restarts_requested": policy.restarts,
    }

    if event_count < policy.minimum_events:
        diagnostics["reason"] = "fewer_than_minimum_events"
        return EtasEstimate(
            event_count=event_count,
            support_state="not_estimable",
            observation_duration_days=observation_duration_days,
            reference_magnitude=reference_magnitude,
            parameters=None,
            converged=False,
            log_likelihood=None,
            restarts_converged=0,
            method_version=policy.method_version,
            calibration_status=policy.calibration_status,
            diagnostics=diagnostics,
        )

    t = np.asarray(event_times_days, dtype=float)
    m = np.asarray(event_magnitudes, dtype=float)
    if observation_duration_days <= 0 or observation_duration_days < float(t.max()):
        diagnostics["reason"] = "observation_duration_shorter_than_last_event"
        return EtasEstimate(
            event_count=event_count,
            support_state="not_estimable",
            observation_duration_days=observation_duration_days,
            reference_magnitude=reference_magnitude,
            parameters=None,
            converged=False,
            log_likelihood=None,
            restarts_converged=0,
            method_version=policy.method_version,
            calibration_status=policy.calibration_status,
            diagnostics=diagnostics,
        )

    bounds = [
        policy.mu_bounds_per_day,
        policy.k0_bounds,
        policy.alpha_bounds,
        policy.c_bounds_days,
        policy.p_bounds,
    ]

    if initial_guess is not None:
        seed_points = [
            np.array(
                [
                    initial_guess.mu_per_day,
                    initial_guess.k0,
                    initial_guess.alpha,
                    initial_guess.c_days,
                    initial_guess.p_exponent,
                ]
            )
        ]
    else:
        crude_mu = event_count / observation_duration_days / 2.0
        seed_points = [np.array([crude_mu, 1.0, 1.0, 0.1, 1.1])]

    rng = np.random.default_rng(policy.restart_seed)
    while len(seed_points) < policy.restarts:
        seed_points.append(np.array([rng.uniform(low, high) for low, high in bounds]))

    best_fit: optimize.OptimizeResult | None = None
    converged_count = 0
    for x0 in seed_points:
        fit = optimize.minimize(
            _negative_log_likelihood,
            x0=x0,
            args=(t, m, reference_magnitude, observation_duration_days),
            method="L-BFGS-B",
            bounds=bounds,
        )
        if not fit.success:
            fit = optimize.minimize(
                _negative_log_likelihood,
                x0=x0,
                args=(t, m, reference_magnitude, observation_duration_days),
                method="Nelder-Mead",
                bounds=bounds,
                options={"xatol": 1e-8, "fatol": 1e-8, "maxiter": 4000},
            )
        if fit.success and math.isfinite(fit.fun):
            converged_count += 1
            if best_fit is None or fit.fun < best_fit.fun:
                best_fit = fit

    diagnostics["restarts_converged"] = converged_count
    if best_fit is None:
        diagnostics["reason"] = "no_restart_converged"
        return EtasEstimate(
            event_count=event_count,
            support_state="not_estimable",
            observation_duration_days=observation_duration_days,
            reference_magnitude=reference_magnitude,
            parameters=None,
            converged=False,
            log_likelihood=None,
            restarts_converged=0,
            method_version=policy.method_version,
            calibration_status=policy.calibration_status,
            diagnostics=diagnostics,
        )

    mu, k0, alpha, c, p = (float(value) for value in best_fit.x)
    parameters = EtasParameters(mu_per_day=mu, k0=k0, alpha=alpha, c_days=c, p_exponent=p)
    diagnostics["log_likelihood"] = -float(best_fit.fun)

    return EtasEstimate(
        event_count=event_count,
        support_state="estimable",
        observation_duration_days=observation_duration_days,
        reference_magnitude=reference_magnitude,
        parameters=parameters,
        converged=True,
        log_likelihood=-float(best_fit.fun),
        restarts_converged=converged_count,
        method_version=policy.method_version,
        calibration_status=policy.calibration_status,
        diagnostics=diagnostics,
    )
