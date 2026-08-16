import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import optimize

from chile_oef.seismicity.modified_omori import _integral_rate

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class SpatiotemporalEtasPolicy:
    version: int = 1
    status: str = "experimental"
    method_version: str = "spatiotemporal_etas_mle_v1"
    calibration_status: str = "uncalibrated_mle_estimator"
    # More parameters than temporal ETAS need more events to identify.
    minimum_events: int = 150
    mu_bounds_per_day: tuple[float, float] = (1e-6, 50.0)
    k0_bounds: tuple[float, float] = (1e-6, 100.0)
    alpha_bounds: tuple[float, float] = (0.0, 5.0)
    c_bounds_days: tuple[float, float] = (1e-4, 10.0)
    p_bounds: tuple[float, float] = (0.3, 3.0)
    d0_bounds_km: tuple[float, float] = (0.01, 300.0)
    gamma_bounds: tuple[float, float] = (0.0, 3.0)
    q_bounds: tuple[float, float] = (1.05, 5.0)
    restarts: int = 6
    restart_seed: int = 20260816


@dataclass(frozen=True)
class SpatiotemporalEtasParameters:
    mu_per_day: float
    k0: float
    alpha: float
    c_days: float
    p_exponent: float
    d0_km: float
    gamma: float
    q_exponent: float


@dataclass(frozen=True)
class SpatiotemporalEtasEstimate:
    event_count: int
    support_state: str
    observation_duration_days: float
    reference_magnitude: float
    parameters: SpatiotemporalEtasParameters | None
    converged: bool
    log_likelihood: float | None
    restarts_converged: int
    method_version: str
    calibration_status: str
    diagnostics: dict[str, Any]


def _haversine_km_matrix(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    d_lat = lat_rad[:, None] - lat_rad[None, :]
    d_lon = lon_rad[:, None] - lon_rad[None, :]
    a = (
        np.sin(d_lat / 2.0) ** 2
        + np.cos(lat_rad[:, None]) * np.cos(lat_rad[None, :]) * np.sin(d_lon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _spatial_density(r_km: np.ndarray, d_km: np.ndarray, q: float) -> np.ndarray:
    """Ogata (1998) isotropic power-law spatial density, a proper 2-D
    density (integrates to 1 over the infinite plane for q > 1):

        f(r; d) = (q-1) / (pi * d^2) * (1 + r^2/d^2)^(-q)
    """
    return (q - 1.0) / (math.pi * d_km**2) * np.power(1.0 + (r_km**2) / (d_km**2), -q)


def _conditional_intensities(
    t: np.ndarray,
    r: np.ndarray,
    m: np.ndarray,
    mc: float,
    mu: float,
    k0: float,
    alpha: float,
    c: float,
    p: float,
    d0: float,
    gamma: float,
    q: float,
    region_area_km2: float,
) -> np.ndarray:
    # lambda(t,x,y) is a spatial density (events/day/km^2): the triggering
    # term already carries those units via the normalized spatial kernel,
    # so mu (a total events/day rate, matching temporal ETAS's mu for
    # interpretability) must be converted to a density here by dividing by
    # the region area -- adding it directly as a bare scalar would be a
    # units mismatch against a per-km^2 density and was caught during
    # development: it let the optimizer collapse to k0=0 with mu absorbing
    # the whole rate, because an unconverted mu of order 1 dwarfs realistic
    # spatial-kernel density values (~0.01/km^2 at these d/q scales).
    mu_density = mu / region_area_km2
    dt = t[:, None] - t[None, :]
    mask = dt > 0.0
    productivity = k0 * np.exp(alpha * (m - mc))
    d_source = d0 * np.exp(gamma * (m - mc))
    temporal_kernel = np.where(mask, 1.0 / np.power(np.where(mask, dt + c, 1.0), p), 0.0)
    spatial_kernel = _spatial_density(r, d_source[None, :], q)
    contributions = np.where(mask, temporal_kernel * spatial_kernel * productivity[None, :], 0.0)
    return mu_density + contributions.sum(axis=1)


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
    """Integral of lambda over [0, duration] x (the whole plane). The
    spatial kernel is a proper density (integrates to 1 over the infinite
    plane for q > 1), so it drops out of this integral exactly the same way
    it does in temporal-only ETAS -- spatial information only affects which
    events get "credit" for triggering which others (the per-event
    intensity terms), not the total expected count. This is also why k0/c/p
    fit here are not required to exactly match a temporal-only fit: the sum
    of per-event log-intensities differs even though this integral doesn't.
    """
    remaining = np.clip(duration_days - t, 0.0, None)
    productivity = k0 * np.exp(alpha * (m - mc))
    per_event_integral = np.array([_integral_rate(c, p, d) for d in remaining])
    return mu * duration_days + float(np.sum(productivity * per_event_integral))


def _negative_log_likelihood(
    params: np.ndarray,
    t: np.ndarray,
    r: np.ndarray,
    m: np.ndarray,
    mc: float,
    duration_days: float,
    region_area_km2: float,
) -> float:
    mu, k0, alpha, c, p, d0, gamma, q = params
    if mu <= 0 or k0 < 0 or c <= 0 or d0 <= 0 or q <= 1.0:
        return math.inf
    intensities = _conditional_intensities(
        t, r, m, mc, mu, k0, alpha, c, p, d0, gamma, q, region_area_km2
    )
    if np.any(intensities <= 0) or not np.all(np.isfinite(intensities)):
        return math.inf
    integral = _integral_of_intensity(t, m, mc, mu, k0, alpha, c, p, duration_days)
    if integral <= 0 or not math.isfinite(integral):
        return math.inf
    log_likelihood = float(np.sum(np.log(intensities))) - integral
    if not math.isfinite(log_likelihood):
        return math.inf
    return -log_likelihood


def estimate_spatiotemporal_etas(
    event_times_days: Sequence[float],
    event_latitudes: Sequence[float],
    event_longitudes: Sequence[float],
    event_magnitudes: Sequence[float],
    *,
    region_area_km2: float,
    reference_magnitude: float,
    observation_duration_days: float,
    policy: SpatiotemporalEtasPolicy | None = None,
    initial_guess: SpatiotemporalEtasParameters | None = None,
) -> SpatiotemporalEtasEstimate:
    """Spatiotemporal ETAS: adds an Ogata (1998) isotropic power-law spatial
    triggering kernel to temporal ETAS's Omori-law temporal kernel:

        lambda(t,x,y) = mu/A + sum_{t_j<t} k0*exp(alpha*(m_j-mc))
                             / (t-t_j+c)^p * f(|x,y - x_j,y_j|; d(m_j))

    where ``A`` is ``region_area_km2``, d(m) = d0*exp(gamma*(m-mc)) lets
    larger events trigger over a wider area, and q controls how fast the
    spatial density decays with distance. lambda is a genuine spatial
    density (events/day/km^2): mu (a total events/day rate, kept in the
    same units as temporal ETAS's mu for interpretability) must be divided
    by the region's area to be added to the density-valued triggering term
    -- omitting that conversion is a real units-mismatch bug caught during
    development (see `_conditional_intensities`), not a hypothetical one.

    Deliberate scoping decision (see docs/PROJECT_STATE.md): the background
    rate is a single homogeneous scalar (mu/A everywhere), NOT the
    spatially-varying rate the smoothed background-rate module
    (`background_rate.py`) already produces. Jointly fitting a
    spatially-varying background together with the triggering kernel is a
    substantially larger undertaking (it changes the integral-of-intensity
    term, which currently drops the spatial kernel out analytically because
    it is a normalized density); doing that properly is future work, not
    silently approximated here. This slice's spatial extent is real and
    fit-worthy on its own: it is exactly the part of the model that answers
    "how far do aftershocks spread," independent of the background term.

    ``reference_magnitude`` (mc) must be a declared, already-estimated Mc,
    per the same discipline as temporal ETAS.
    """
    policy = policy or SpatiotemporalEtasPolicy()
    event_count = len(event_times_days)
    diagnostics: dict[str, Any] = {
        "estimator": "spatiotemporal_etas_mle",
        "restarts_requested": policy.restarts,
        "background_scope": "homogeneous_scalar_mu_not_spatially_varying",
    }

    if event_count < policy.minimum_events:
        diagnostics["reason"] = "fewer_than_minimum_events"
        return SpatiotemporalEtasEstimate(
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
    lat = np.asarray(event_latitudes, dtype=float)
    lon = np.asarray(event_longitudes, dtype=float)
    m = np.asarray(event_magnitudes, dtype=float)
    if observation_duration_days <= 0 or observation_duration_days < float(t.max()):
        diagnostics["reason"] = "observation_duration_shorter_than_last_event"
        return SpatiotemporalEtasEstimate(
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

    r = _haversine_km_matrix(lat, lon)

    bounds = [
        policy.mu_bounds_per_day,
        policy.k0_bounds,
        policy.alpha_bounds,
        policy.c_bounds_days,
        policy.p_bounds,
        policy.d0_bounds_km,
        policy.gamma_bounds,
        policy.q_bounds,
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
                    initial_guess.d0_km,
                    initial_guess.gamma,
                    initial_guess.q_exponent,
                ]
            )
        ]
    else:
        crude_mu = event_count / observation_duration_days / 2.0
        seed_points = [np.array([crude_mu, 1.0, 1.0, 0.1, 1.1, 5.0, 0.5, 1.5])]

    rng = np.random.default_rng(policy.restart_seed)
    while len(seed_points) < policy.restarts:
        seed_points.append(np.array([rng.uniform(low, high) for low, high in bounds]))

    best_fit: optimize.OptimizeResult | None = None
    converged_count = 0
    for x0 in seed_points:
        fit = optimize.minimize(
            _negative_log_likelihood,
            x0=x0,
            args=(t, r, m, reference_magnitude, observation_duration_days, region_area_km2),
            method="L-BFGS-B",
            bounds=bounds,
        )
        if not fit.success:
            fit = optimize.minimize(
                _negative_log_likelihood,
                x0=x0,
                args=(t, r, m, reference_magnitude, observation_duration_days, region_area_km2),
                method="Nelder-Mead",
                bounds=bounds,
                options={"xatol": 1e-8, "fatol": 1e-8, "maxiter": 6000},
            )
        if fit.success and math.isfinite(fit.fun):
            converged_count += 1
            if best_fit is None or fit.fun < best_fit.fun:
                best_fit = fit

    diagnostics["restarts_converged"] = converged_count
    if best_fit is None:
        diagnostics["reason"] = "no_restart_converged"
        return SpatiotemporalEtasEstimate(
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

    mu, k0, alpha, c, p, d0, gamma, q = (float(value) for value in best_fit.x)
    parameters = SpatiotemporalEtasParameters(
        mu_per_day=mu,
        k0=k0,
        alpha=alpha,
        c_days=c,
        p_exponent=p,
        d0_km=d0,
        gamma=gamma,
        q_exponent=q,
    )
    diagnostics["log_likelihood"] = -float(best_fit.fun)

    return SpatiotemporalEtasEstimate(
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
