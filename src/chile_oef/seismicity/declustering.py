import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from scipy import optimize

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class DeclusteringPolicy:
    version: int = 1
    status: str = "experimental"
    method_version: str = "nearest_neighbor_declustering_v1"
    # Zaliapin & Ben-Zion (2013) use ~1.6 for southern California; no
    # Chile-specific fractal dimension has been fit here yet, so this is a
    # declared, uncalibrated default -- same pattern as the tectonic
    # classifier's uncalibrated_rule_baseline.
    calibration_status: str = "uncalibrated_default_fractal_dimension"
    fractal_dimension: float = 1.6
    em_max_iterations: int = 200
    em_tolerance: float = 1e-8
    em_seed: int = 20260816
    minimum_events_for_threshold_fit: int = 50


@dataclass(frozen=True)
class EventForDeclustering:
    event_id: Any
    event_time: datetime
    latitude: float
    longitude: float
    magnitude: float


@dataclass(frozen=True)
class EventDeclustering:
    event_id: Any
    parent_event_id: Any | None
    log10_eta: float | None
    is_background: bool | None


@dataclass(frozen=True)
class DeclusteringResult:
    event_count: int
    classified_event_count: int
    background_event_count: int
    log_eta_threshold: float | None
    fractal_dimension: float
    b_value_used: float
    method_version: str
    calibration_status: str
    classifications: tuple[EventDeclustering, ...]
    diagnostics: dict[str, Any]


def _haversine_km(lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = np.radians(lat2), np.radians(lon2)
    d_lat = lat2_rad - lat1_rad
    d_lon = lon2_rad - lon1_rad
    a = np.sin(d_lat / 2.0) ** 2 + math.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(d_lon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _nearest_neighbor_distances(
    ordered: Sequence[EventForDeclustering], *, fractal_dimension: float, b_value: float
) -> list[tuple[Any, float]]:
    """For each event (except the first, chronologically), the (parent_id,
    log10 nearest-neighbor distance eta) to its closest predecessor in the
    Baiesi & Paczuski (2004) / Zaliapin & Ben-Zion (2013) space-time-
    magnitude metric. Small eta means "close relative to what its parent's
    magnitude would predict" (likely triggered); large eta means
    independent (likely background).
    """
    n = len(ordered)
    times = np.array([event.event_time.timestamp() for event in ordered], dtype=float)
    lats = np.array([event.latitude for event in ordered], dtype=float)
    lons = np.array([event.longitude for event in ordered], dtype=float)
    mags = np.array([event.magnitude for event in ordered], dtype=float)

    results: list[tuple[Any, float]] = []
    for index in range(1, n):
        dt_days = (times[index] - times[:index]) / 86400.0
        dt_days = np.maximum(dt_days, 1.0 / 86400.0)  # floor at one second
        r_km = _haversine_km(lats[index], lons[index], lats[:index], lons[:index])
        r_km = np.maximum(r_km, 1e-3)  # floor at 1 m to avoid log(0)
        eta = dt_days * (r_km**fractal_dimension) * (10.0 ** (-b_value * mags[:index]))
        parent_index = int(np.argmin(eta))
        results.append((ordered[parent_index].event_id, math.log10(float(eta[parent_index]))))
    return results


def _gaussian_pdf(values: np.ndarray, mean: float, variance: float) -> np.ndarray:
    return np.exp(-0.5 * (values - mean) ** 2 / variance) / math.sqrt(2.0 * math.pi * variance)


def _fit_two_component_threshold(
    log10_eta_values: np.ndarray, *, max_iterations: int, tolerance: float
) -> tuple[float, dict[str, float]]:
    """Univariate two-component Gaussian mixture via EM on log10(eta).
    Returns the crossover point between the two fitted components -- the
    Zaliapin & Ben-Zion (2013) threshold separating triggered pairs (lower
    mode) from background pairs (upper mode) -- and the fitted parameters.
    """
    x = np.asarray(log10_eta_values, dtype=float)
    n = x.size
    order = np.argsort(x)
    low_half, high_half = x[order[: n // 2]], x[order[n // 2 :]]
    mu = np.array([low_half.mean(), high_half.mean()])
    var = np.array([low_half.var() + 1e-6, high_half.var() + 1e-6])
    weight = np.array([0.5, 0.5])

    previous_log_likelihood = -math.inf
    log_likelihood = previous_log_likelihood
    for _ in range(max_iterations):
        densities = np.stack([weight[k] * _gaussian_pdf(x, mu[k], var[k]) for k in range(2)])
        total = np.clip(densities.sum(axis=0), 1e-300, None)
        responsibilities = densities / total
        log_likelihood = float(np.sum(np.log(total)))

        component_weight_sum = responsibilities.sum(axis=1)
        mu = (responsibilities * x).sum(axis=1) / component_weight_sum
        var = (responsibilities * (x - mu[:, None]) ** 2).sum(axis=1) / component_weight_sum
        var = np.maximum(var, 1e-8)
        weight = component_weight_sum / n

        if abs(log_likelihood - previous_log_likelihood) < tolerance:
            break
        previous_log_likelihood = log_likelihood

    low, high = (0, 1) if mu[0] <= mu[1] else (1, 0)
    mu_low, mu_high = float(mu[low]), float(mu[high])
    var_low, var_high = float(var[low]), float(var[high])
    weight_low, weight_high = float(weight[low]), float(weight[high])

    threshold = _solve_gaussian_crossover(
        mu_low, var_low, weight_low, mu_high, var_high, weight_high
    )
    diagnostics = {
        "mu_triggered": mu_low,
        "mu_background": mu_high,
        "var_triggered": var_low,
        "var_background": var_high,
        "weight_triggered": weight_low,
        "weight_background": weight_high,
        "log_likelihood": log_likelihood,
    }
    return threshold, diagnostics


def _solve_gaussian_crossover(
    mu_low: float,
    var_low: float,
    weight_low: float,
    mu_high: float,
    var_high: float,
    weight_high: float,
) -> float:
    def difference(x: float) -> float:
        density_low = (
            weight_low
            * math.exp(-0.5 * (x - mu_low) ** 2 / var_low)
            / math.sqrt(2.0 * math.pi * var_low)
        )
        density_high = (
            weight_high
            * math.exp(-0.5 * (x - mu_high) ** 2 / var_high)
            / math.sqrt(2.0 * math.pi * var_high)
        )
        return density_low - density_high

    if mu_low >= mu_high:
        return (mu_low + mu_high) / 2.0
    left, right = difference(mu_low), difference(mu_high)
    if left == 0.0:
        return mu_low
    if right == 0.0:
        return mu_high
    if left * right > 0.0:
        # No sign change between the two means (can happen with very
        # unequal variances/weights): fall back to the midpoint rather than
        # returning a root outside the physically meaningful interval.
        return (mu_low + mu_high) / 2.0
    return float(optimize.brentq(difference, mu_low, mu_high))


def decluster(
    events: Sequence[EventForDeclustering],
    *,
    b_value: float,
    policy: DeclusteringPolicy | None = None,
) -> DeclusteringResult:
    policy = policy or DeclusteringPolicy()
    ordered = sorted(events, key=lambda event: event.event_time)
    event_count = len(ordered)
    diagnostics: dict[str, Any] = {
        "estimator": "nearest_neighbor_declustering",
        "fractal_dimension": policy.fractal_dimension,
        "b_value_used": b_value,
    }

    if event_count == 0:
        return DeclusteringResult(
            event_count=0,
            classified_event_count=0,
            background_event_count=0,
            log_eta_threshold=None,
            fractal_dimension=policy.fractal_dimension,
            b_value_used=b_value,
            method_version=policy.method_version,
            calibration_status=policy.calibration_status,
            classifications=(),
            diagnostics={**diagnostics, "reason": "no_events"},
        )

    pairs = _nearest_neighbor_distances(
        ordered, fractal_dimension=policy.fractal_dimension, b_value=b_value
    )
    log_eta_by_index = {index + 1: log10_eta for index, (_parent, log10_eta) in enumerate(pairs)}
    parent_by_index = {index + 1: parent for index, (parent, _log10_eta) in enumerate(pairs)}

    finite_log_eta = np.array(
        [value for value in log_eta_by_index.values() if math.isfinite(value)]
    )
    threshold: float | None = None
    if finite_log_eta.size >= policy.minimum_events_for_threshold_fit:
        threshold, fit_diagnostics = _fit_two_component_threshold(
            finite_log_eta,
            max_iterations=policy.em_max_iterations,
            tolerance=policy.em_tolerance,
        )
        diagnostics.update(fit_diagnostics)
    else:
        diagnostics["reason"] = "fewer_than_minimum_events_for_threshold_fit"

    classifications: list[EventDeclustering] = []
    # The very first event chronologically has no earlier candidate parent
    # in this window: it is trivially independent (background) within the
    # observed window, not "unclassified".
    classifications.append(
        EventDeclustering(
            event_id=ordered[0].event_id,
            parent_event_id=None,
            log10_eta=None,
            is_background=True,
        )
    )
    for index in range(1, event_count):
        log10_eta = log_eta_by_index[index]
        is_background = threshold is not None and log10_eta >= threshold
        classifications.append(
            EventDeclustering(
                event_id=ordered[index].event_id,
                parent_event_id=parent_by_index[index],
                log10_eta=log10_eta,
                is_background=is_background if threshold is not None else None,
            )
        )

    classified = [c for c in classifications if c.is_background is not None]
    background = [c for c in classified if c.is_background]

    return DeclusteringResult(
        event_count=event_count,
        classified_event_count=len(classified),
        background_event_count=len(background),
        log_eta_threshold=threshold,
        fractal_dimension=policy.fractal_dimension,
        b_value_used=b_value,
        method_version=policy.method_version,
        calibration_status=policy.calibration_status,
        classifications=tuple(classifications),
        diagnostics=diagnostics,
    )
