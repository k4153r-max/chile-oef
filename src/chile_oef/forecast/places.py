"""Named places for public readout of an already-issued forecast.

A place estimate is the Poisson probability of at least one event in a
circular neighborhood, obtained by summing expected counts of estimable
cells whose centers fall inside the radius. It inherits the forecast
run's calibration_status -- it is not a new, calibrated city product.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0
DEFAULT_RADIUS_KM = 40.0

# Major Chilean cities, north to south. Coordinates are city centers.
PLACES: tuple[dict[str, float | str], ...] = (
    {"id": "arica", "name": "Arica", "latitude": -18.478, "longitude": -70.321},
    {"id": "iquique", "name": "Iquique", "latitude": -20.230, "longitude": -70.135},
    {"id": "antofagasta", "name": "Antofagasta", "latitude": -23.650, "longitude": -70.400},
    {"id": "copiapo", "name": "Copiapó", "latitude": -27.366, "longitude": -70.332},
    {"id": "la_serena", "name": "La Serena", "latitude": -29.903, "longitude": -71.250},
    {"id": "valparaiso", "name": "Valparaíso", "latitude": -33.047, "longitude": -71.613},
    {"id": "santiago", "name": "Santiago", "latitude": -33.448, "longitude": -70.669},
    {"id": "rancagua", "name": "Rancagua", "latitude": -34.170, "longitude": -70.744},
    {"id": "talca", "name": "Talca", "latitude": -35.426, "longitude": -71.655},
    {"id": "concepcion", "name": "Concepción", "latitude": -36.827, "longitude": -73.050},
    {"id": "temuco", "name": "Temuco", "latitude": -38.736, "longitude": -72.590},
    {"id": "valdivia", "name": "Valdivia", "latitude": -39.814, "longitude": -73.246},
    {"id": "puerto_montt", "name": "Puerto Montt", "latitude": -41.469, "longitude": -72.942},
    {"id": "coyhaique", "name": "Coyhaique", "latitude": -45.571, "longitude": -72.068},
    {"id": "punta_arenas", "name": "Punta Arenas", "latitude": -53.163, "longitude": -70.917},
)


@dataclass(frozen=True)
class PlaceEstimate:
    place_id: str
    name: str
    latitude: float
    longitude: float
    radius_km: float
    cell_count: int
    expected_count: float | None
    probability_at_least_one: float | None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlamb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlamb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def bounding_box(
    latitude: float, longitude: float, radius_km: float
) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.32
    cos_lat = max(0.15, math.cos(math.radians(latitude)))
    dlon = radius_km / (111.32 * cos_lat)
    return latitude - dlat, latitude + dlat, longitude - dlon, longitude + dlon


def aggregate_expected_counts(
    cells: list[tuple[float, float, float]],
    *,
    latitude: float,
    longitude: float,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> tuple[int, float]:
    """Return (n_cells, sum of expected counts) inside the radius."""
    total = 0.0
    count = 0
    for cell_lat, cell_lon, expected in cells:
        if haversine_km(latitude, longitude, cell_lat, cell_lon) <= radius_km:
            total += expected
            count += 1
    return count, total


def poisson_at_least_one(expected_count: float) -> float:
    if expected_count <= 0:
        return 0.0
    if expected_count > 50:
        return 1.0
    return 1.0 - math.exp(-expected_count)


def estimate_place(
    cells: list[tuple[float, float, float]],
    place: dict[str, float | str],
    *,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> PlaceEstimate:
    n_cells, expected = aggregate_expected_counts(
        cells,
        latitude=float(place["latitude"]),
        longitude=float(place["longitude"]),
        radius_km=radius_km,
    )
    probability = poisson_at_least_one(expected) if n_cells else None
    return PlaceEstimate(
        place_id=str(place["id"]),
        name=str(place["name"]),
        latitude=float(place["latitude"]),
        longitude=float(place["longitude"]),
        radius_km=radius_km,
        cell_count=n_cells,
        expected_count=expected if n_cells else None,
        probability_at_least_one=probability,
    )
