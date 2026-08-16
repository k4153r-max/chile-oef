import math

import numpy as np
import pytest

from chile_oef.seismicity.background_rate import (
    BackgroundEventLocation,
    BackgroundRatePolicy,
    GridCellTarget,
    estimate_background_rate,
)

EARTH_RADIUS_KM = 6371.0088


def _padded_grid(
    *, min_lat: float, max_lat: float, min_lon: float, max_lon: float, resolution: float, pad: float
) -> list[GridCellTarget]:
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
    return cells


def test_no_background_events_returns_no_cell_rates() -> None:
    result = estimate_background_rate([], [], observation_duration_days=365.0)
    assert result.cell_rates == ()
    assert result.background_event_count == 0


def test_non_positive_duration_returns_no_cell_rates() -> None:
    locations = [BackgroundEventLocation(latitude=-33.0, longitude=-71.0)]
    cells = [
        GridCellTarget(cell_id="c1", center_latitude=-33.0, center_longitude=-71.0, area_km2=10.0)
    ]
    result = estimate_background_rate(locations, cells, observation_duration_days=0.0)
    assert result.cell_rates == ()


def test_kernel_density_conserves_total_event_mass_over_a_padded_grid() -> None:
    """Sum(density_per_km2 * cell_area_km2) over a grid padded well beyond
    the adaptive bandwidths must recover the background event count -- this
    is a mass-conservation identity of the kernel density estimate, not a
    tunable threshold, so the tolerance is tight.
    """
    rng = np.random.default_rng(1)
    n = 200
    lats = rng.uniform(-34.0, -32.0, size=n)
    lons = rng.uniform(-72.0, -70.0, size=n)
    locations = [
        BackgroundEventLocation(latitude=float(a), longitude=float(o))
        for a, o in zip(lats, lons, strict=True)
    ]
    cells = _padded_grid(
        min_lat=-34.0, max_lat=-32.0, min_lon=-72.0, max_lon=-70.0, resolution=0.1, pad=1.5
    )

    result = estimate_background_rate(locations, cells, observation_duration_days=730.0)
    total_mass = sum(
        cell_rate.density_per_km2 * cell.area_km2
        for cell_rate, cell in zip(result.cell_rates, cells, strict=True)
    )
    assert total_mass == pytest.approx(n, rel=0.01)


def test_kernel_density_without_padding_leaks_mass_at_the_edges() -> None:
    """The same identity computed on a grid that does NOT extend beyond the
    event scatter must recover noticeably less than the true count -- this
    is the expected, documented edge-effect limitation of a finite-domain
    kernel density estimate, not a bug, and this test pins that it is real
    (so a future "fix" that silently makes it disappear gets noticed).
    """
    rng = np.random.default_rng(1)
    n = 200
    lats = rng.uniform(-34.0, -32.0, size=n)
    lons = rng.uniform(-72.0, -70.0, size=n)
    locations = [
        BackgroundEventLocation(latitude=float(a), longitude=float(o))
        for a, o in zip(lats, lons, strict=True)
    ]
    unpadded_cells = _padded_grid(
        min_lat=-34.0, max_lat=-32.0, min_lon=-72.0, max_lon=-70.0, resolution=0.1, pad=0.0
    )

    result = estimate_background_rate(locations, unpadded_cells, observation_duration_days=730.0)
    total_mass = sum(
        cell_rate.density_per_km2 * cell.area_km2
        for cell_rate, cell in zip(result.cell_rates, unpadded_cells, strict=True)
    )
    assert total_mass < 0.9 * n


def test_total_annual_rate_matches_event_count_over_duration() -> None:
    rng = np.random.default_rng(2)
    n = 150
    lats = rng.uniform(-34.0, -32.0, size=n)
    lons = rng.uniform(-72.0, -70.0, size=n)
    locations = [
        BackgroundEventLocation(latitude=float(a), longitude=float(o))
        for a, o in zip(lats, lons, strict=True)
    ]
    cells = _padded_grid(
        min_lat=-34.0, max_lat=-32.0, min_lon=-72.0, max_lon=-70.0, resolution=0.1, pad=1.5
    )
    duration_days = 500.0
    result = estimate_background_rate(locations, cells, observation_duration_days=duration_days)
    total_rate_per_year = sum(cell_rate.rate_per_year for cell_rate in result.cell_rates)
    expected_rate_per_year = n / (duration_days / 365.25)
    assert total_rate_per_year == pytest.approx(expected_rate_per_year, rel=0.01)


def test_denser_regions_receive_a_smaller_adaptive_bandwidth() -> None:
    """The adaptive kernel is supposed to sharpen where events are dense and
    widen where they are sparse -- verified indirectly through the resulting
    density: a probe cell inside a tight cluster should see a much higher
    density than an equally-sized probe cell in the sparse region.
    """
    rng = np.random.default_rng(3)
    dense_cluster = rng.normal(loc=[-33.0, -71.0], scale=[0.01, 0.01], size=(100, 2))
    sparse_scatter = rng.uniform([-34.0, -73.0], [-33.5, -72.5], size=(20, 2))
    locations = [
        BackgroundEventLocation(latitude=float(lat), longitude=float(lon))
        for lat, lon in np.vstack([dense_cluster, sparse_scatter])
    ]
    probe_cells = [
        GridCellTarget(
            cell_id="dense", center_latitude=-33.0, center_longitude=-71.0, area_km2=1.0
        ),
        GridCellTarget(
            cell_id="sparse", center_latitude=-33.75, center_longitude=-72.75, area_km2=1.0
        ),
    ]
    result = estimate_background_rate(
        locations, probe_cells, observation_duration_days=365.0, policy=BackgroundRatePolicy()
    )
    by_id = {cell_rate.cell_id: cell_rate for cell_rate in result.cell_rates}
    assert by_id["dense"].density_per_km2 > by_id["sparse"].density_per_km2
