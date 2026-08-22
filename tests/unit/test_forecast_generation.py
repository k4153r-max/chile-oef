import math

import numpy as np
import pytest

from chile_oef.forecast.generation import generate_forecast_cells
from chile_oef.forecast.specification import MagnitudeBin
from chile_oef.seismicity.background_rate import GridCellTarget
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasParameters

EARTH_RADIUS_KM = 6371.0088

STANDARD_BINS = (
    MagnitudeBin(lower=3.0, upper=4.0),
    MagnitudeBin(lower=4.0, upper=5.0),
    MagnitudeBin(lower=5.0, upper=6.0),
    MagnitudeBin(lower=6.0, upper=7.0),
    MagnitudeBin(lower=7.0, upper=None),
)


def _padded_grid(
    *, min_lat: float, max_lat: float, min_lon: float, max_lon: float, resolution: float, pad: float
) -> tuple[list[GridCellTarget], float]:
    lat_centers = np.arange(min_lat - pad + resolution / 2, max_lat + pad, resolution)
    lon_centers = np.arange(min_lon - pad + resolution / 2, max_lon + pad, resolution)
    cells: list[GridCellTarget] = []
    for lat in lat_centers:
        height_km = resolution * (math.pi / 180.0) * EARTH_RADIUS_KM
        width_km = resolution * (math.pi / 180.0) * EARTH_RADIUS_KM * math.cos(math.radians(lat))
        area_km2 = height_km * width_km
        for lon in lon_centers:
            cells.append(
                GridCellTarget(
                    cell_id=f"{lat:.4f}_{lon:.4f}",
                    center_latitude=float(lat),
                    center_longitude=float(lon),
                    area_km2=area_km2,
                )
            )
    region_height_km = (max_lat - min_lat + 2 * pad) * (math.pi / 180.0) * EARTH_RADIUS_KM
    region_width_km = (
        (max_lon - min_lon + 2 * pad)
        * (math.pi / 180.0)
        * EARTH_RADIUS_KM
        * math.cos(math.radians((min_lat + max_lat) / 2.0))
    )
    return cells, region_height_km * region_width_km


def test_no_prior_events_gives_background_only_forecast() -> None:
    params = SpatiotemporalEtasParameters(
        mu_per_day=1.0,
        k0=0.05,
        alpha=1.0,
        c_days=0.1,
        p_exponent=1.2,
        d0_km=5.0,
        gamma=0.5,
        q_exponent=1.8,
    )
    cells, region_area = _padded_grid(
        min_lat=-34.0, max_lat=-32.0, min_lon=-72.0, max_lon=-70.0, resolution=0.5, pad=0.0
    )
    result = generate_forecast_cells(
        prior_event_times_days=[],
        prior_event_latitudes=[],
        prior_event_longitudes=[],
        prior_event_magnitudes=[],
        etas_parameters=params,
        b_value=1.0,
        reference_magnitude=3.0,
        region_area_km2=region_area,
        validity_start_days=100.0,
        validity_end_days=101.0,
        cells=cells,
        magnitude_bins=STANDARD_BINS,
    )
    assert result.total_expected_count_all_magnitudes == pytest.approx(params.mu_per_day * 1.0)
    # Uniform background: every cell's (3.0, 4.0) bin expected count must be
    # exactly proportional to that cell's area (cell area itself varies
    # slightly with latitude on a regular lat/lon grid, so equal counts
    # would be the wrong expectation here).
    by_cell = {cell.cell_id: cell for cell in cells}
    ratios = {
        cf.expected_count / by_cell[cf.cell_id].area_km2
        for cf in result.cell_forecasts
        if cf.magnitude_lower == 3.0
    }
    assert max(ratios) - min(ratios) < 1e-12


def test_bins_below_reference_magnitude_are_not_estimable() -> None:
    params = SpatiotemporalEtasParameters(
        mu_per_day=1.0,
        k0=0.05,
        alpha=1.0,
        c_days=0.1,
        p_exponent=1.2,
        d0_km=5.0,
        gamma=0.5,
        q_exponent=1.8,
    )
    cells = [
        GridCellTarget(cell_id="c1", center_latitude=-33.0, center_longitude=-71.0, area_km2=100.0)
    ]
    bins = (MagnitudeBin(lower=2.0, upper=3.0), MagnitudeBin(lower=3.0, upper=4.0))
    result = generate_forecast_cells(
        prior_event_times_days=[],
        prior_event_latitudes=[],
        prior_event_longitudes=[],
        prior_event_magnitudes=[],
        etas_parameters=params,
        b_value=1.0,
        reference_magnitude=3.0,
        region_area_km2=10000.0,
        validity_start_days=0.0,
        validity_end_days=1.0,
        cells=cells,
        magnitude_bins=bins,
    )
    below_mc = [cf for cf in result.cell_forecasts if cf.magnitude_lower == 2.0][0]
    at_mc = [cf for cf in result.cell_forecasts if cf.magnitude_lower == 3.0][0]
    assert below_mc.support_state == "not_estimable"
    assert below_mc.expected_count is None
    assert below_mc.probability_at_least_one is None
    assert at_mc.support_state == "estimable"
    assert at_mc.expected_count is not None


def test_gutenberg_richter_bin_fractions_decay_geometrically() -> None:
    """With b=1.0, each successive *finite-width* one-magnitude-unit bin
    must carry exactly 1/10th the expected count of the previous one -- the
    defining property of the Gutenberg-Richter law. This does not extend to
    the transition into the final open-ended bin: a finite bin's fraction is
    a *difference* of two cumulative tails (tail(low) - tail(low+1) =
    0.9*tail(low) for a one-unit-wide bin), while the open-ended bin is the
    raw tail(low) itself with nothing subtracted, so that specific ratio is
    1/9 of the preceding finite bin, not 1/10 -- a real property of the
    model, not something to paper over with a looser tolerance.
    """
    params = SpatiotemporalEtasParameters(
        mu_per_day=1.0,
        k0=0.0,
        alpha=1.0,
        c_days=0.1,
        p_exponent=1.2,
        d0_km=5.0,
        gamma=0.5,
        q_exponent=1.8,
    )
    cells = [
        GridCellTarget(
            cell_id="c1", center_latitude=-33.0, center_longitude=-71.0, area_km2=10000.0
        )
    ]
    result = generate_forecast_cells(
        prior_event_times_days=[],
        prior_event_latitudes=[],
        prior_event_longitudes=[],
        prior_event_magnitudes=[],
        etas_parameters=params,
        b_value=1.0,
        reference_magnitude=3.0,
        region_area_km2=10000.0,
        validity_start_days=0.0,
        validity_end_days=1.0,
        cells=cells,
        magnitude_bins=STANDARD_BINS,
    )
    finite_bin_counts = [
        cf.expected_count for cf in result.cell_forecasts if cf.magnitude_upper is not None
    ]
    for earlier, later in zip(finite_bin_counts, finite_bin_counts[1:], strict=False):
        assert later == pytest.approx(earlier / 10.0, rel=1e-6)

    open_ended = next(cf for cf in result.cell_forecasts if cf.magnitude_upper is None)
    assert open_ended.expected_count == pytest.approx(finite_bin_counts[-1] / 9.0, rel=1e-6)


def test_mass_conservation_over_a_padded_grid_with_triggering() -> None:
    """Summed over a grid padded well beyond the triggering kernel's reach,
    the sum of all cells' all-bin expected counts must recover the
    region-wide total (background + triggering, all magnitudes) -- the
    same mass-conservation identity already relied on in
    tests/unit/test_background_rate.py, now including the GR magnitude
    split (whose fractions must themselves sum to 1 above Mc).
    """
    rng = np.random.default_rng(3)
    n = 40
    t = sorted(rng.uniform(0.0, 90.0, size=n).tolist())
    lat = rng.uniform(-33.5, -32.5, size=n).tolist()
    lon = rng.uniform(-71.5, -70.5, size=n).tolist()
    m = [3.5] * n
    params = SpatiotemporalEtasParameters(
        mu_per_day=1.0,
        k0=0.05,
        alpha=1.0,
        c_days=0.1,
        p_exponent=1.2,
        d0_km=5.0,
        gamma=0.5,
        q_exponent=1.8,
    )
    cells, region_area = _padded_grid(
        min_lat=-33.5, max_lat=-32.5, min_lon=-71.5, max_lon=-70.5, resolution=0.2, pad=1.5
    )
    result = generate_forecast_cells(
        prior_event_times_days=t,
        prior_event_latitudes=lat,
        prior_event_longitudes=lon,
        prior_event_magnitudes=m,
        etas_parameters=params,
        b_value=1.0,
        reference_magnitude=3.0,
        region_area_km2=region_area,
        validity_start_days=90.0,
        validity_end_days=91.0,
        cells=cells,
        magnitude_bins=STANDARD_BINS,
    )
    total_from_cells = sum(
        cf.expected_count for cf in result.cell_forecasts if cf.expected_count is not None
    )
    assert total_from_cells == pytest.approx(result.total_expected_count_all_magnitudes, rel=0.02)


def test_method_and_calibration_metadata() -> None:
    params = SpatiotemporalEtasParameters(
        mu_per_day=1.0,
        k0=0.0,
        alpha=1.0,
        c_days=0.1,
        p_exponent=1.2,
        d0_km=5.0,
        gamma=0.5,
        q_exponent=1.8,
    )
    cells = [
        GridCellTarget(cell_id="c1", center_latitude=-33.0, center_longitude=-71.0, area_km2=100.0)
    ]
    result = generate_forecast_cells(
        prior_event_times_days=[],
        prior_event_latitudes=[],
        prior_event_longitudes=[],
        prior_event_magnitudes=[],
        etas_parameters=params,
        b_value=1.0,
        reference_magnitude=3.0,
        region_area_km2=10000.0,
        validity_start_days=0.0,
        validity_end_days=1.0,
        cells=cells,
        magnitude_bins=STANDARD_BINS,
    )
    assert result.method_version == "etas_gr_grid_forecast_v1"
    assert result.calibration_status == "uncalibrated_point_forecast"
    assert result.diagnostics["uncertainty_propagated"] is False
    assert result.diagnostics["background_spatial_model"] == "homogeneous_area_weighted"
    assert result.diagnostics["etas_stability"]["state"] == "subcritical_lifetime_branching"


def test_adaptive_background_redistributes_mu_and_preserves_total_mass() -> None:
    params = SpatiotemporalEtasParameters(
        mu_per_day=1.0,
        k0=0.0,
        alpha=0.5,
        c_days=0.1,
        p_exponent=1.2,
        d0_km=5.0,
        gamma=0.0,
        q_exponent=1.8,
    )
    cells = [
        GridCellTarget(
            cell_id="quiet", center_latitude=-34.0, center_longitude=-71.0, area_km2=100.0
        ),
        GridCellTarget(
            cell_id="active", center_latitude=-33.0, center_longitude=-71.0, area_km2=100.0
        ),
    ]
    result = generate_forecast_cells(
        prior_event_times_days=[],
        prior_event_latitudes=[],
        prior_event_longitudes=[],
        prior_event_magnitudes=[],
        etas_parameters=params,
        b_value=1.0,
        reference_magnitude=3.0,
        region_area_km2=200.0,
        validity_start_days=0.0,
        validity_end_days=1.0,
        cells=cells,
        magnitude_bins=(MagnitudeBin(lower=3.0, upper=None),),
        background_cell_weights={"quiet": 1.0, "active": 9.0},
    )
    by_cell = {row.cell_id: row.expected_count for row in result.cell_forecasts}
    assert by_cell["active"] == pytest.approx(0.9)
    assert by_cell["quiet"] == pytest.approx(0.1)
    assert sum(by_cell.values()) == pytest.approx(params.mu_per_day)
    assert result.method_version == "etas_gr_adaptive_background_grid_forecast_v2"
    assert result.diagnostics["background_spatial_model"] == "adaptive_kernel_normalized_to_etas_mu"


def test_adaptive_background_refuses_incomplete_cell_coverage() -> None:
    params = SpatiotemporalEtasParameters(
        mu_per_day=1.0,
        k0=0.0,
        alpha=0.5,
        c_days=0.1,
        p_exponent=1.2,
        d0_km=5.0,
        gamma=0.0,
        q_exponent=1.8,
    )
    cells = [
        GridCellTarget(cell_id="a", center_latitude=-34.0, center_longitude=-71.0, area_km2=100.0),
        GridCellTarget(cell_id="b", center_latitude=-33.0, center_longitude=-71.0, area_km2=100.0),
    ]
    with pytest.raises(ValueError, match="missing_count=1"):
        generate_forecast_cells(
            prior_event_times_days=[],
            prior_event_latitudes=[],
            prior_event_longitudes=[],
            prior_event_magnitudes=[],
            etas_parameters=params,
            b_value=1.0,
            reference_magnitude=3.0,
            region_area_km2=200.0,
            validity_start_days=0.0,
            validity_end_days=1.0,
            cells=cells,
            magnitude_bins=(MagnitudeBin(lower=3.0, upper=None),),
            background_cell_weights={"a": 1.0},
        )


def test_p_not_above_one_is_reported_as_finite_horizon_only() -> None:
    params = SpatiotemporalEtasParameters(
        mu_per_day=1.0,
        k0=0.05,
        alpha=0.547,
        c_days=0.036,
        p_exponent=0.882,
        d0_km=20.2,
        gamma=0.0,
        q_exponent=1.52,
    )
    result = generate_forecast_cells(
        prior_event_times_days=[],
        prior_event_latitudes=[],
        prior_event_longitudes=[],
        prior_event_magnitudes=[],
        etas_parameters=params,
        b_value=1.1215,
        reference_magnitude=5.0,
        region_area_km2=100.0,
        validity_start_days=0.0,
        validity_end_days=7.0,
        cells=[
            GridCellTarget(
                cell_id="a", center_latitude=-33.0, center_longitude=-71.0, area_km2=100.0
            )
        ],
        magnitude_bins=(MagnitudeBin(lower=5.0, upper=None),),
    )
    stability = result.diagnostics["etas_stability"]
    assert stability["state"] == "finite_horizon_only_p_not_above_one"
    assert stability["finite_horizon_mean_direct_offspring"] == pytest.approx(0.3136, rel=1e-3)
    assert stability["lifetime_mean_direct_offspring"] is None
