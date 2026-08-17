import math

from chile_oef.forecast.places import (
    aggregate_expected_counts,
    estimate_place,
    haversine_km,
    poisson_at_least_one,
)


def test_haversine_santiago_valparaiso_is_about_100_km() -> None:
    distance = haversine_km(-33.448, -70.669, -33.047, -71.613)
    assert 95 < distance < 120


def test_aggregate_counts_only_cells_inside_radius() -> None:
    cells = [
        (-33.45, -70.67, 0.01),
        (-33.45, -70.67, 0.02),
        (-20.0, -70.0, 9.0),
    ]
    count, total = aggregate_expected_counts(cells, latitude=-33.45, longitude=-70.67, radius_km=40)
    assert count == 2
    assert total == 0.03


def test_poisson_at_least_one_matches_1_minus_exp() -> None:
    assert poisson_at_least_one(0) == 0.0
    assert poisson_at_least_one(0.01) == 1.0 - math.exp(-0.01)
    assert poisson_at_least_one(80) == 1.0


def test_estimate_place_empty_neighborhood_is_not_a_fabricated_zero() -> None:
    place = {"id": "santiago", "name": "Santiago", "latitude": -33.45, "longitude": -70.67}
    result = estimate_place([], place)
    assert result.cell_count == 0
    assert result.expected_count is None
    assert result.probability_at_least_one is None
