import math

import pytest

from chile_oef.tectonics.slab2 import (
    GeographicBounds,
    SlabAssetBundle,
    circular_weighted_degrees,
    iter_slab_records,
    normalize_longitude,
    parse_xyz_grid,
)


def test_strike_interpolation_wraps_across_north() -> None:
    result = circular_weighted_degrees([359.0, 1.0], [0.5, 0.5])
    assert result == pytest.approx(0.0, abs=1e-12)


def test_xyz_parser_normalizes_longitude_depth_and_excludes_nan_and_bounds() -> None:
    content = b"288.0,-33.0,-25.0\n288.05,-33.0,nan\n250.0,-33.0,-99.0\n"
    parsed = parse_xyz_grid(
        content,
        absolute_value=True,
        bounds=GeographicBounds(
            min_latitude=-34,
            max_latitude=-32,
            min_longitude=-73,
            max_longitude=-71,
        ),
    )
    assert normalize_longitude(288.0) == -72.0
    assert list(parsed.values()) == [25.0]


def test_slab_bundle_merges_on_grid_key_and_preserves_missing_optional_value() -> None:
    bundle = SlabAssetBundle(
        depth=b"288.0,-33.0,-25.0\n",
        dip=b"288.0,-33.0,20.0\n",
        strike=b"288.0,-33.0,359.0\n",
        thickness=b"288.0,-33.0,55.0\n",
        uncertainty=b"288.05,-33.0,4.0\n",
    )
    record = next(iter_slab_records(bundle))
    assert (record.longitude, record.latitude, record.depth_km) == (-72.0, -33.0, 25.0)
    assert record.dip_degrees == 20.0
    assert record.strike_degrees == 359.0
    assert record.thickness_km == 55.0
    assert record.uncertainty_km is None
    assert math.isfinite(record.depth_km)
