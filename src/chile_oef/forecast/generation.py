import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from chile_oef.forecast.specification import MagnitudeBin
from chile_oef.seismicity.background_rate import GridCellTarget
from chile_oef.seismicity.modified_omori import _integral_rate
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasParameters, _spatial_density

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class ForecastGenerationPolicy:
    version: int = 1
    status: str = "experimental"
    method_version: str = "etas_gr_grid_forecast_v1"
    # No parameter uncertainty (from the ETAS/GR MLE fits) is propagated
    # into these probabilities yet -- point estimates only. A declared,
    # documented limitation, not a calibrated forecast probability in the
    # full sense forecast-contract.md eventually wants.
    calibration_status: str = "uncalibrated_point_forecast"


@dataclass(frozen=True)
class CellMagnitudeBinForecast:
    cell_id: str
    magnitude_lower: float
    magnitude_upper: float | None
    support_state: str
    expected_count: float | None
    probability_at_least_one: float | None


@dataclass(frozen=True)
class ForecastGenerationResult:
    cell_forecasts: tuple[CellMagnitudeBinForecast, ...]
    total_expected_count_all_magnitudes: float
    method_version: str
    calibration_status: str
    diagnostics: dict[str, Any]


def _haversine_km(lat1: float, lon1: float, lats2: np.ndarray, lons2: np.ndarray) -> np.ndarray:
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lats2_rad, lons2_rad = np.radians(lats2), np.radians(lons2)
    d_lat = lats2_rad - lat1_rad
    d_lon = lons2_rad - lon1_rad
    a = np.sin(d_lat / 2.0) ** 2 + math.cos(lat1_rad) * np.cos(lats2_rad) * np.sin(d_lon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _magnitude_bin_fraction(
    bin_lower: float, bin_upper: float | None, *, b_value: float, reference_magnitude: float
) -> float | None:
    """Fraction of all events with magnitude >= reference_magnitude that
    fall in [bin_lower, bin_upper) under the fitted Gutenberg-Richter law.
    None (not_estimable) if the bin's lower edge is below the declared Mc --
    forecast-contract.md: "target threshold below Mc" is a mandatory
    not-estimable condition, not something to compute anyway with a
    formula that would silently exceed 1.
    """
    if bin_lower < reference_magnitude:
        return None
    lower_fraction = 10.0 ** (-b_value * (bin_lower - reference_magnitude))
    if bin_upper is None:
        return lower_fraction
    upper_fraction = 10.0 ** (-b_value * (bin_upper - reference_magnitude))
    return lower_fraction - upper_fraction


def _etas_stability_diagnostics(
    *,
    parameters: SpatiotemporalEtasParameters,
    b_value: float,
    horizon_days: float,
) -> dict[str, Any]:
    """Report branching/stationarity diagnostics without changing the fit."""
    beta = b_value * math.log(10.0)
    magnitude_moment_finite = parameters.alpha < beta
    magnitude_factor = beta / (beta - parameters.alpha) if magnitude_moment_finite else None
    horizon_integral = _integral_rate(parameters.c_days, parameters.p_exponent, horizon_days)
    finite_horizon_direct_offspring = (
        parameters.k0 * magnitude_factor * horizon_integral
        if magnitude_factor is not None
        else None
    )

    lifetime_direct_offspring: float | None
    if magnitude_factor is not None and parameters.p_exponent > 1.0:
        lifetime_integral = parameters.c_days ** (1.0 - parameters.p_exponent) / (
            parameters.p_exponent - 1.0
        )
        lifetime_direct_offspring = parameters.k0 * magnitude_factor * lifetime_integral
    else:
        lifetime_direct_offspring = None

    if not magnitude_moment_finite:
        state = "non_finite_magnitude_productivity"
    elif parameters.p_exponent <= 1.0:
        state = "finite_horizon_only_p_not_above_one"
    elif lifetime_direct_offspring is not None and lifetime_direct_offspring >= 1.0:
        state = "supercritical_lifetime_branching"
    else:
        state = "subcritical_lifetime_branching"

    return {
        "state": state,
        "beta": beta,
        "alpha_below_beta": magnitude_moment_finite,
        "p_above_one": parameters.p_exponent > 1.0,
        "finite_horizon_mean_direct_offspring": finite_horizon_direct_offspring,
        "lifetime_mean_direct_offspring": lifetime_direct_offspring,
        "forecast_horizon_days": horizon_days,
    }


def generate_forecast_cells(
    *,
    prior_event_times_days: Sequence[float],
    prior_event_latitudes: Sequence[float],
    prior_event_longitudes: Sequence[float],
    prior_event_magnitudes: Sequence[float],
    etas_parameters: SpatiotemporalEtasParameters,
    b_value: float,
    reference_magnitude: float,
    region_area_km2: float,
    validity_start_days: float,
    validity_end_days: float,
    cells: Sequence[GridCellTarget],
    magnitude_bins: Sequence[MagnitudeBin],
    background_cell_weights: Mapping[str, float] | None = None,
    policy: ForecastGenerationPolicy | None = None,
) -> ForecastGenerationResult:
    """Grid-cell x magnitude-bin forecast from an already-fit spatiotemporal
    ETAS model and an already-fit Gutenberg-Richter b-value, over
    [validity_start_days, validity_end_days). Only events strictly before
    validity_start contribute (the caller is responsible for filtering to
    "prior" events -- same availability invariant as everywhere else).

    Per cell, the total expected count of all events at/above
    reference_magnitude is:

        E(cell) = mu * (cell_area / region_area) * duration
                + sum_j k0*exp(alpha*(m_j-mc)) * temporal_integral_j
                      * f(r_j_to_cell_center; d_j, q) * cell_area

    (background allocated proportional to area since it is spatially
    homogeneous by this project's spatiotemporal ETAS scoping decision; each
    prior event's triggering contribution uses the point-density
    approximation at the cell center, the same approximation
    background_rate.py already uses and documents). This total is then
    split across magnitude bins by the Gutenberg-Richter law, and converted
    to a probability of at least one event via the standard Poisson
    approximation `1 - exp(-expected_count)`.
    """
    policy = policy or ForecastGenerationPolicy()
    duration_days = validity_end_days - validity_start_days
    diagnostics: dict[str, Any] = {
        "estimator": "etas_gr_grid_forecast",
        "duration_days": duration_days,
        "cell_count": len(cells),
        "prior_event_count": len(prior_event_times_days),
        "spatial_approximation": "point_density_at_cell_center",
        "uncertainty_propagated": False,
        "etas_stability": _etas_stability_diagnostics(
            parameters=etas_parameters,
            b_value=b_value,
            horizon_days=duration_days,
        ),
    }

    normalized_background_weights: dict[str, float] | None = None
    if background_cell_weights is not None:
        missing = {cell.cell_id for cell in cells}.difference(background_cell_weights)
        if missing:
            raise ValueError(
                "adaptive background weights do not cover every forecast cell; "
                f"missing_count={len(missing)}"
            )
        if any(
            weight < 0 or not math.isfinite(weight) for weight in background_cell_weights.values()
        ):
            raise ValueError("adaptive background weights must be finite and non-negative")
        total_background_weight = math.fsum(background_cell_weights[cell.cell_id] for cell in cells)
        if total_background_weight <= 0:
            raise ValueError("adaptive background weights must have positive total mass")
        normalized_background_weights = {
            cell.cell_id: background_cell_weights[cell.cell_id] / total_background_weight
            for cell in cells
        }
        diagnostics["background_spatial_model"] = "adaptive_kernel_normalized_to_etas_mu"
        diagnostics["background_raw_weight_total"] = total_background_weight
    else:
        diagnostics["background_spatial_model"] = "homogeneous_area_weighted"

    t = np.asarray(prior_event_times_days, dtype=float)
    lat = np.asarray(prior_event_latitudes, dtype=float)
    lon = np.asarray(prior_event_longitudes, dtype=float)
    m = np.asarray(prior_event_magnitudes, dtype=float)

    productivity = etas_parameters.k0 * np.exp(etas_parameters.alpha * (m - reference_magnitude))
    temporal_integral = np.array(
        [
            _integral_rate(
                etas_parameters.c_days, etas_parameters.p_exponent, validity_end_days - tj
            )
            - _integral_rate(
                etas_parameters.c_days, etas_parameters.p_exponent, validity_start_days - tj
            )
            for tj in t
        ]
    )
    weighted_productivity = productivity * temporal_integral
    d_source = etas_parameters.d0_km * np.exp(etas_parameters.gamma * (m - reference_magnitude))

    background_total = etas_parameters.mu_per_day * duration_days
    triggering_total = float(np.sum(weighted_productivity))
    total_expected_count_all_magnitudes = background_total + triggering_total
    diagnostics["background_total_expected_count"] = background_total
    diagnostics["triggering_total_expected_count"] = triggering_total

    bin_fractions = [
        _magnitude_bin_fraction(
            bin_spec.lower, bin_spec.upper, b_value=b_value, reference_magnitude=reference_magnitude
        )
        for bin_spec in magnitude_bins
    ]

    cell_forecasts: list[CellMagnitudeBinForecast] = []
    for cell in cells:
        if len(t) > 0:
            r_to_cell = _haversine_km(cell.center_latitude, cell.center_longitude, lat, lon)
            spatial_density_at_cell = _spatial_density(
                r_to_cell, d_source, etas_parameters.q_exponent
            )
            triggering_contribution = float(
                np.sum(weighted_productivity * spatial_density_at_cell * cell.area_km2)
            )
        else:
            triggering_contribution = 0.0
        if normalized_background_weights is None:
            background_weight = cell.area_km2 / region_area_km2
        else:
            background_weight = normalized_background_weights[cell.cell_id]
        background_contribution = etas_parameters.mu_per_day * background_weight * duration_days
        cell_total_expected_count = background_contribution + triggering_contribution

        for bin_spec, fraction in zip(magnitude_bins, bin_fractions, strict=True):
            if fraction is None:
                cell_forecasts.append(
                    CellMagnitudeBinForecast(
                        cell_id=cell.cell_id,
                        magnitude_lower=bin_spec.lower,
                        magnitude_upper=bin_spec.upper,
                        support_state="not_estimable",
                        expected_count=None,
                        probability_at_least_one=None,
                    )
                )
                continue
            expected_count = cell_total_expected_count * fraction
            probability = 1.0 - math.exp(-expected_count)
            cell_forecasts.append(
                CellMagnitudeBinForecast(
                    cell_id=cell.cell_id,
                    magnitude_lower=bin_spec.lower,
                    magnitude_upper=bin_spec.upper,
                    support_state="estimable",
                    expected_count=expected_count,
                    probability_at_least_one=probability,
                )
            )

    return ForecastGenerationResult(
        cell_forecasts=tuple(cell_forecasts),
        total_expected_count_all_magnitudes=total_expected_count_all_magnitudes,
        method_version=(
            "etas_gr_adaptive_background_grid_forecast_v2"
            if normalized_background_weights is not None
            else policy.method_version
        ),
        calibration_status=policy.calibration_status,
        diagnostics=diagnostics,
    )
