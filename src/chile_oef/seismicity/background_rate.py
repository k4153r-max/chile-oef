import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class BackgroundRatePolicy:
    version: int = 1
    status: str = "experimental"
    method_version: str = "adaptive_kernel_background_rate_v1"
    # k and the bandwidth floor are declared, uncalibrated defaults (no
    # cross-validated bandwidth selection has been done for Chile) -- same
    # pattern as declustering's fractal dimension.
    calibration_status: str = "uncalibrated_default_bandwidth"
    k_nearest_neighbors: int = 5
    minimum_bandwidth_km: float = 1.0


@dataclass(frozen=True)
class BackgroundEventLocation:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class GridCellTarget:
    cell_id: str
    center_latitude: float
    center_longitude: float
    area_km2: float


@dataclass(frozen=True)
class CellBackgroundRate:
    cell_id: str
    density_per_km2: float
    rate_per_year: float


@dataclass(frozen=True)
class BackgroundRateResult:
    background_event_count: int
    observation_duration_days: float
    k_nearest_neighbors: int
    method_version: str
    calibration_status: str
    cell_rates: tuple[CellBackgroundRate, ...]
    diagnostics: dict[str, Any]


def _haversine_km_matrix(
    lat1: float, lon1: float, lats2: np.ndarray, lons2: np.ndarray
) -> np.ndarray:
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lats2_rad, lons2_rad = np.radians(lats2), np.radians(lons2)
    d_lat = lats2_rad - lat1_rad
    d_lon = lons2_rad - lon1_rad
    a = np.sin(d_lat / 2.0) ** 2 + math.cos(lat1_rad) * np.cos(lats2_rad) * np.sin(d_lon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _adaptive_bandwidths(
    lats: np.ndarray, lons: np.ndarray, *, k: int, minimum_km: float
) -> np.ndarray:
    """Distance from each background event to its k-th nearest *other*
    background event (Helmstetter, Kagan & Jackson, 2007), floored so
    near-duplicate locations do not produce a near-zero, spuriously
    concentrated kernel.
    """
    n = lats.size
    bandwidths = np.empty(n)
    for i in range(n):
        distances = np.sort(_haversine_km_matrix(lats[i], lons[i], lats, lons))
        k_effective = min(k, n - 1)
        bandwidths[i] = max(float(distances[k_effective]), minimum_km)
    return bandwidths


def estimate_background_rate(
    locations: Sequence[BackgroundEventLocation],
    cells: Sequence[GridCellTarget],
    *,
    observation_duration_days: float,
    policy: BackgroundRatePolicy | None = None,
) -> BackgroundRateResult:
    """Adaptive-kernel smoothed seismicity background rate (Helmstetter,
    Kagan & Jackson, 2007). Each background event contributes a 2-D Gaussian
    kernel with bandwidth adaptive to local event density (its distance to
    its k-th nearest neighbor); summing all kernels at a target point gives
    a spatial density (events/km^2) that integrates, over the whole region,
    to approximately the background event count. Dividing by the
    observation duration (in years) converts that density into an annual
    rate per unit area, and multiplying by each grid cell's area (from the
    Phase 2 grid) gives an expected annual event count per cell.
    """
    policy = policy or BackgroundRatePolicy()
    event_count = len(locations)
    diagnostics: dict[str, Any] = {
        "estimator": "adaptive_kernel_background_rate",
        "k_nearest_neighbors": policy.k_nearest_neighbors,
        "minimum_bandwidth_km": policy.minimum_bandwidth_km,
    }
    if event_count == 0 or observation_duration_days <= 0:
        diagnostics["reason"] = "no_background_events_or_non_positive_duration"
        return BackgroundRateResult(
            background_event_count=event_count,
            observation_duration_days=observation_duration_days,
            k_nearest_neighbors=policy.k_nearest_neighbors,
            method_version=policy.method_version,
            calibration_status=policy.calibration_status,
            cell_rates=(),
            diagnostics=diagnostics,
        )

    lats = np.array([location.latitude for location in locations], dtype=float)
    lons = np.array([location.longitude for location in locations], dtype=float)
    bandwidths = _adaptive_bandwidths(
        lats, lons, k=policy.k_nearest_neighbors, minimum_km=policy.minimum_bandwidth_km
    )
    observation_duration_years = observation_duration_days / 365.25

    cell_rates: list[CellBackgroundRate] = []
    for cell in cells:
        distances = _haversine_km_matrix(cell.center_latitude, cell.center_longitude, lats, lons)
        density_per_km2 = float(
            np.sum(np.exp(-0.5 * (distances / bandwidths) ** 2) / (2.0 * math.pi * bandwidths**2))
        )
        rate_per_year = density_per_km2 * cell.area_km2 / observation_duration_years
        cell_rates.append(
            CellBackgroundRate(
                cell_id=cell.cell_id,
                density_per_km2=density_per_km2,
                rate_per_year=rate_per_year,
            )
        )

    diagnostics["mean_bandwidth_km"] = float(np.mean(bandwidths))
    diagnostics["min_bandwidth_km"] = float(np.min(bandwidths))
    diagnostics["max_bandwidth_km"] = float(np.max(bandwidths))
    diagnostics["observation_duration_years"] = observation_duration_years

    return BackgroundRateResult(
        background_event_count=event_count,
        observation_duration_days=observation_duration_days,
        k_nearest_neighbors=policy.k_nearest_neighbors,
        method_version=policy.method_version,
        calibration_status=policy.calibration_status,
        cell_rates=tuple(cell_rates),
        diagnostics=diagnostics,
    )
