import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import optimize


@dataclass(frozen=True)
class ModifiedOmoriPolicy:
    version: int = 1
    status: str = "experimental"
    method_version: str = "modified_omori_mle_v1"
    calibration_status: str = "uncalibrated_mle_estimator"
    minimum_events_per_sequence: int = 20
    c_min_days: float = 1e-4
    c_max_days: float = 10.0
    p_min: float = 0.3
    p_max: float = 3.0
    initial_c_days: float = 0.1
    initial_p: float = 1.0


@dataclass(frozen=True)
class ModifiedOmoriEstimate:
    event_count: int
    support_state: str
    observation_duration_days: float
    k_productivity: float | None
    c_days: float | None
    p_exponent: float | None
    converged: bool
    method_version: str
    calibration_status: str
    diagnostics: dict[str, Any]


def _integral_rate(c: float, p: float, duration_days: float) -> float:
    """Integral of K/(t+c)^p over [0, duration_days], with K factored out."""
    if abs(p - 1.0) < 1e-8:
        return math.log(duration_days + c) - math.log(c)
    return ((duration_days + c) ** (1.0 - p) - c ** (1.0 - p)) / (1.0 - p)


def estimate_modified_omori(
    event_times_days: Sequence[float],
    *,
    observation_duration_days: float,
    policy: ModifiedOmoriPolicy | None = None,
) -> ModifiedOmoriEstimate:
    """Modified Omori-Utsu law n(t) = K / (t + c)^p fit by maximum
    likelihood (Ogata, 1983) to the arrival times of one aftershock
    sequence, where t is time since the triggering (root) event and
    ``observation_duration_days`` is the time from that root event to the
    end of the analysis window -- not the last observed event's time, which
    would truncation-bias the fit toward observed activity and understate
    the true decay tail.

    K is profiled out analytically given (c, p) (the profile MLE), leaving a
    2-parameter numerical optimization over (c, p).
    """
    policy = policy or ModifiedOmoriPolicy()
    event_count = len(event_times_days)
    diagnostics: dict[str, Any] = {
        "estimator": "modified_omori_mle",
        "observation_duration_days": observation_duration_days,
    }

    if event_count < policy.minimum_events_per_sequence:
        diagnostics["reason"] = "fewer_than_minimum_events_per_sequence"
        return ModifiedOmoriEstimate(
            event_count=event_count,
            support_state="not_estimable",
            observation_duration_days=observation_duration_days,
            k_productivity=None,
            c_days=None,
            p_exponent=None,
            converged=False,
            method_version=policy.method_version,
            calibration_status=policy.calibration_status,
            diagnostics=diagnostics,
        )

    t = np.asarray(event_times_days, dtype=float)
    duration = observation_duration_days
    if duration <= 0 or duration < float(t.max()):
        diagnostics["reason"] = "observation_duration_shorter_than_last_event"
        return ModifiedOmoriEstimate(
            event_count=event_count,
            support_state="not_estimable",
            observation_duration_days=observation_duration_days,
            k_productivity=None,
            c_days=None,
            p_exponent=None,
            converged=False,
            method_version=policy.method_version,
            calibration_status=policy.calibration_status,
            diagnostics=diagnostics,
        )

    def negative_profile_log_likelihood(params: np.ndarray) -> float:
        c, p = params
        if c <= 0:
            return math.inf
        integral = _integral_rate(c, p, duration)
        if integral <= 0 or not math.isfinite(integral):
            return math.inf
        sum_log = float(np.sum(np.log(t + c)))
        profile_log_likelihood = (
            event_count * math.log(event_count)
            - event_count * math.log(integral)
            - p * sum_log
            - event_count
        )
        if not math.isfinite(profile_log_likelihood):
            return math.inf
        return -profile_log_likelihood

    bounds = [(policy.c_min_days, policy.c_max_days), (policy.p_min, policy.p_max)]
    x0 = np.array([policy.initial_c_days, policy.initial_p])
    fit = optimize.minimize(
        negative_profile_log_likelihood, x0=x0, method="L-BFGS-B", bounds=bounds
    )
    diagnostics["optimizer"] = "L-BFGS-B"
    if not fit.success:
        # L-BFGS-B's line search can abort on this likelihood surface for
        # some sequences (steep curvature near the bounds); Nelder-Mead
        # is gradient-free and slower but far more robust here, so it is a
        # deliberate fallback, not silently masking a real non-convergence.
        bounded_nelder_mead = optimize.minimize(
            negative_profile_log_likelihood,
            x0=x0,
            method="Nelder-Mead",
            bounds=bounds,
            options={"xatol": 1e-8, "fatol": 1e-8, "maxiter": 2000},
        )
        diagnostics["optimizer"] = "Nelder-Mead (L-BFGS-B fallback)"
        diagnostics["lbfgsb_message"] = str(fit.message)
        fit = bounded_nelder_mead
    if not fit.success:
        diagnostics["reason"] = "did_not_converge"
        diagnostics["optimizer_message"] = str(fit.message)
        return ModifiedOmoriEstimate(
            event_count=event_count,
            support_state="not_estimable",
            observation_duration_days=observation_duration_days,
            k_productivity=None,
            c_days=None,
            p_exponent=None,
            converged=False,
            method_version=policy.method_version,
            calibration_status=policy.calibration_status,
            diagnostics=diagnostics,
        )

    c, p = (float(value) for value in fit.x)
    integral = _integral_rate(c, p, duration)
    k = event_count / integral
    diagnostics["profile_log_likelihood"] = -float(fit.fun)

    return ModifiedOmoriEstimate(
        event_count=event_count,
        support_state="estimable",
        observation_duration_days=observation_duration_days,
        k_productivity=k,
        c_days=c,
        p_exponent=p,
        converged=True,
        method_version=policy.method_version,
        calibration_status=policy.calibration_status,
        diagnostics=diagnostics,
    )
