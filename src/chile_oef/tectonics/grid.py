import hashlib
import math
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

import orjson
from geoalchemy2.elements import WKTElement
from sqlalchemy import insert
from sqlalchemy.orm import Session

from chile_oef.db.models import SeismicCell, SpatialGrid

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class GridDefinition:
    id: str
    resolution_degrees: Decimal
    min_latitude: Decimal
    max_latitude: Decimal
    min_longitude: Decimal
    max_longitude: Decimal
    status: str = "draft"

    def validate(self) -> None:
        if self.resolution_degrees <= 0:
            raise ValueError("grid resolution must be positive")
        if self.min_latitude >= self.max_latitude:
            raise ValueError("invalid latitude bounds")
        if self.min_longitude >= self.max_longitude:
            raise ValueError("invalid longitude bounds")
        lat_steps = (self.max_latitude - self.min_latitude) / self.resolution_degrees
        lon_steps = (self.max_longitude - self.min_longitude) / self.resolution_degrees
        if lat_steps != lat_steps.to_integral_value():
            raise ValueError("latitude span is not divisible by resolution")
        if lon_steps != lon_steps.to_integral_value():
            raise ValueError("longitude span is not divisible by resolution")

    @property
    def row_count(self) -> int:
        self.validate()
        return int((self.max_latitude - self.min_latitude) / self.resolution_degrees)

    @property
    def column_count(self) -> int:
        self.validate()
        return int((self.max_longitude - self.min_longitude) / self.resolution_degrees)

    @property
    def cell_count(self) -> int:
        return self.row_count * self.column_count

    @property
    def digest(self) -> str:
        document = {
            "id": self.id,
            "resolution_degrees": str(self.resolution_degrees),
            "min_latitude": str(self.min_latitude),
            "max_latitude": str(self.max_latitude),
            "min_longitude": str(self.min_longitude),
            "max_longitude": str(self.max_longitude),
            "status": self.status,
            "crs": "EPSG:4326",
        }
        return hashlib.sha256(orjson.dumps(document, option=orjson.OPT_SORT_KEYS)).hexdigest()


@dataclass(frozen=True)
class CellDefinition:
    id: str
    row_index: int
    column_index: int
    min_latitude: Decimal
    max_latitude: Decimal
    min_longitude: Decimal
    max_longitude: Decimal
    center_latitude: float
    center_longitude: float
    area_km2: float

    @property
    def polygon_wkt(self) -> str:
        west, east = self.min_longitude, self.max_longitude
        south, north = self.min_latitude, self.max_latitude
        return (
            f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
        )


def spherical_cell_area_km2(
    south: Decimal,
    north: Decimal,
    west: Decimal,
    east: Decimal,
) -> float:
    delta_lon = math.radians(float(east - west))
    latitude_term = abs(math.sin(math.radians(float(north))) - math.sin(math.radians(float(south))))
    return EARTH_RADIUS_KM**2 * delta_lon * latitude_term


def iter_cells(definition: GridDefinition) -> Iterator[CellDefinition]:
    definition.validate()
    resolution = definition.resolution_degrees
    for row in range(definition.row_count):
        south = definition.min_latitude + resolution * row
        north = south + resolution
        for column in range(definition.column_count):
            west = definition.min_longitude + resolution * column
            east = west + resolution
            yield CellDefinition(
                id=f"{definition.id}:r{row:04d}:c{column:04d}",
                row_index=row,
                column_index=column,
                min_latitude=south,
                max_latitude=north,
                min_longitude=west,
                max_longitude=east,
                center_latitude=float((south + north) / 2),
                center_longitude=float((west + east) / 2),
                area_km2=spherical_cell_area_km2(south, north, west, east),
            )


class GridService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, definition: GridDefinition, *, batch_size: int = 5000) -> SpatialGrid:
        definition.validate()
        if self.session.get(SpatialGrid, definition.id) is not None:
            raise ValueError(f"grid {definition.id!r} already exists")
        grid = SpatialGrid(
            id=definition.id,
            resolution_degrees=float(definition.resolution_degrees),
            min_latitude=float(definition.min_latitude),
            max_latitude=float(definition.max_latitude),
            min_longitude=float(definition.min_longitude),
            max_longitude=float(definition.max_longitude),
            crs="EPSG:4326",
            status=definition.status,
            definition_sha256=definition.digest,
            metadata_json={
                "row_count": definition.row_count,
                "column_count": definition.column_count,
                "cell_count": definition.cell_count,
                "area_method": "spherical_quadrilateral_wgs84_mean_radius",
            },
        )
        self.session.add(grid)
        self.session.flush()
        batch: list[dict[str, object]] = []
        for cell in iter_cells(definition):
            batch.append(
                {
                    "id": cell.id,
                    "grid_id": definition.id,
                    "row_index": cell.row_index,
                    "column_index": cell.column_index,
                    "center_latitude": cell.center_latitude,
                    "center_longitude": cell.center_longitude,
                    "area_km2": cell.area_km2,
                    "geometry": WKTElement(cell.polygon_wkt, srid=4326),
                }
            )
            if len(batch) >= batch_size:
                self.session.execute(insert(SeismicCell), batch)
                batch.clear()
        if batch:
            self.session.execute(insert(SeismicCell), batch)
        self.session.commit()
        return grid
