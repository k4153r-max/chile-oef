import math
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from geoalchemy2.elements import WKTElement
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from chile_oef.db.models import SlabNode, TectonicRelease

GridKey = tuple[int, int]


@dataclass(frozen=True)
class GeographicBounds:
    min_latitude: float = -60.0
    max_latitude: float = -15.0
    min_longitude: float = -82.0
    max_longitude: float = -62.0

    def contains(self, latitude: float, longitude: float) -> bool:
        return (
            self.min_latitude <= latitude <= self.max_latitude
            and self.min_longitude <= longitude <= self.max_longitude
        )


@dataclass(frozen=True)
class SlabAssetBundle:
    depth: bytes
    dip: bytes
    strike: bytes
    thickness: bytes
    uncertainty: bytes


@dataclass(frozen=True)
class SlabNodeRecord:
    longitude_index: int
    latitude_index: int
    longitude: float
    latitude: float
    depth_km: float
    dip_degrees: float | None
    strike_degrees: float | None
    thickness_km: float | None
    uncertainty_km: float | None


@dataclass(frozen=True)
class SlabSample:
    depth_km: float
    dip_degrees: float | None
    strike_degrees: float | None
    thickness_km: float | None
    uncertainty_km: float | None
    interpolation: str
    contributing_nodes: int


def normalize_longitude(longitude: float) -> float:
    return longitude - 360.0 if longitude > 180.0 else longitude


def coordinate_index(value: float, *, origin: float, resolution: float) -> int:
    return int(round((value - origin) / resolution))


def circular_weighted_degrees(values: list[float], weights: list[float]) -> float:
    if len(values) != len(weights) or not values:
        raise ValueError("circular values and weights must have equal nonzero length")
    radians = [math.radians(value) for value in values]
    sine = sum(math.sin(value) * weight for value, weight in zip(radians, weights, strict=True))
    cosine = sum(math.cos(value) * weight for value, weight in zip(radians, weights, strict=True))
    if math.isclose(sine, 0.0, abs_tol=1e-15) and math.isclose(cosine, 0.0, abs_tol=1e-15):
        raise ValueError("circular mean is undefined for antipodal directions")
    result = math.degrees(math.atan2(sine, cosine)) % 360.0
    return 0.0 if math.isclose(result, 360.0, abs_tol=1e-12) else result


def parse_xyz_grid(
    content: bytes,
    *,
    resolution: float = 0.05,
    bounds: GeographicBounds | None = None,
    absolute_value: bool = False,
) -> dict[GridKey, float]:
    bounds = bounds or GeographicBounds()
    output: dict[GridKey, float] = {}
    for line_number, raw_line in enumerate(content.decode("ascii").splitlines(), start=1):
        if not raw_line.strip():
            continue
        columns = raw_line.split(",")
        if len(columns) != 3:
            raise ValueError(f"Slab2 XYZ line {line_number} does not have three columns")
        longitude = normalize_longitude(float(columns[0]))
        latitude = float(columns[1])
        value = float(columns[2])
        if math.isnan(value) or not bounds.contains(latitude, longitude):
            continue
        if absolute_value:
            value = abs(value)
        key = (
            coordinate_index(longitude, origin=-180.0, resolution=resolution),
            coordinate_index(latitude, origin=-90.0, resolution=resolution),
        )
        if key in output:
            raise ValueError(f"duplicate Slab2 grid node at {longitude}, {latitude}")
        output[key] = value
    return output


def iter_slab_records(
    bundle: SlabAssetBundle,
    *,
    resolution: float = 0.05,
    bounds: GeographicBounds | None = None,
) -> Iterator[SlabNodeRecord]:
    bounds = bounds or GeographicBounds()
    depth = parse_xyz_grid(
        bundle.depth,
        resolution=resolution,
        bounds=bounds,
        absolute_value=True,
    )
    other = {
        "dip": parse_xyz_grid(bundle.dip, resolution=resolution, bounds=bounds),
        "strike": parse_xyz_grid(bundle.strike, resolution=resolution, bounds=bounds),
        "thickness": parse_xyz_grid(
            bundle.thickness,
            resolution=resolution,
            bounds=bounds,
            absolute_value=True,
        ),
        "uncertainty": parse_xyz_grid(
            bundle.uncertainty,
            resolution=resolution,
            bounds=bounds,
            absolute_value=True,
        ),
    }
    for (longitude_index, latitude_index), depth_km in sorted(depth.items()):
        longitude = -180.0 + longitude_index * resolution
        latitude = -90.0 + latitude_index * resolution
        dip = other["dip"].get((longitude_index, latitude_index))
        strike = other["strike"].get((longitude_index, latitude_index))
        if dip is not None and not 0.0 <= dip <= 90.0:
            raise ValueError(f"invalid Slab2 dip {dip} at {longitude}, {latitude}")
        if strike is not None and not 0.0 <= strike <= 360.0:
            raise ValueError(f"invalid Slab2 strike {strike} at {longitude}, {latitude}")
        yield SlabNodeRecord(
            longitude_index=longitude_index,
            latitude_index=latitude_index,
            longitude=longitude,
            latitude=latitude,
            depth_km=depth_km,
            dip_degrees=dip,
            strike_degrees=strike,
            thickness_km=other["thickness"].get((longitude_index, latitude_index)),
            uncertainty_km=other["uncertainty"].get((longitude_index, latitude_index)),
        )


class SlabService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def load_nodes(
        self,
        release: TectonicRelease,
        bundle: SlabAssetBundle,
        *,
        resolution: float = 0.05,
        bounds: GeographicBounds | None = None,
        batch_size: int = 5000,
    ) -> int:
        if release.status != "building":
            raise ValueError("Slab2 nodes can only be loaded into a building release")
        if release.source_id != "slab2_south_america_2018":
            raise ValueError("Slab2 release has the wrong source")
        if (
            self.session.scalar(
                select(SlabNode.id).where(SlabNode.release_id == release.id).limit(1)
            )
            is not None
        ):
            raise ValueError("release already contains slab nodes")
        count = 0
        batch: list[dict[str, object]] = []
        for node in iter_slab_records(bundle, resolution=resolution, bounds=bounds):
            batch.append(
                {
                    "release_id": release.id,
                    "longitude_index": node.longitude_index,
                    "latitude_index": node.latitude_index,
                    "longitude": node.longitude,
                    "latitude": node.latitude,
                    "depth_km": node.depth_km,
                    "dip_degrees": node.dip_degrees,
                    "strike_degrees": node.strike_degrees,
                    "thickness_km": node.thickness_km,
                    "uncertainty_km": node.uncertainty_km,
                    "geometry": WKTElement(
                        f"POINT({node.longitude} {node.latitude})",
                        srid=4326,
                    ),
                }
            )
            count += 1
            if len(batch) >= batch_size:
                self.session.execute(insert(SlabNode), batch)
                batch.clear()
        if batch:
            self.session.execute(insert(SlabNode), batch)
        release.status = "ready"
        release.metadata_json = {
            **release.metadata_json,
            "node_count": count,
            "resolution_degrees": resolution,
            "bounds": (bounds or GeographicBounds()).__dict__,
        }
        self.session.commit()
        return count


class SlabRepository:
    def __init__(self, session: Session, release_id: uuid.UUID, *, resolution: float = 0.05):
        self.session = session
        self.release_id = release_id
        self.resolution = resolution

    def sample(self, *, latitude: float, longitude: float) -> SlabSample | None:
        lon_scaled = (longitude + 180.0) / self.resolution
        lat_scaled = (latitude + 90.0) / self.resolution
        lon_low, lon_high = math.floor(lon_scaled), math.ceil(lon_scaled)
        lat_low, lat_high = math.floor(lat_scaled), math.ceil(lat_scaled)
        nodes = list(
            self.session.scalars(
                select(SlabNode).where(
                    SlabNode.release_id == self.release_id,
                    SlabNode.longitude_index.in_((lon_low, lon_high)),
                    SlabNode.latitude_index.in_((lat_low, lat_high)),
                )
            )
        )
        by_key = {(node.longitude_index, node.latitude_index): node for node in nodes}
        required = {
            (lon_low, lat_low),
            (lon_low, lat_high),
            (lon_high, lat_low),
            (lon_high, lat_high),
        }
        if not required.issubset(by_key):
            return None
        selected = [by_key[key] for key in sorted(required)]
        if len(required) == 1:
            return self._sample_from_values(selected, [1.0], "exact_node")
        x = lon_scaled - lon_low if lon_high != lon_low else 0.0
        y = lat_scaled - lat_low if lat_high != lat_low else 0.0
        weights_by_key = {
            (lon_low, lat_low): (1.0 - x) * (1.0 - y),
            (lon_high, lat_low): x * (1.0 - y),
            (lon_low, lat_high): (1.0 - x) * y,
            (lon_high, lat_high): x * y,
        }
        weights = [weights_by_key[(node.longitude_index, node.latitude_index)] for node in selected]
        return self._sample_from_values(selected, weights, "bilinear")

    @staticmethod
    def _sample_from_values(
        nodes: list[SlabNode],
        weights: list[float],
        interpolation: str,
    ) -> SlabSample:
        def weighted(attribute: str) -> float | None:
            values = [getattr(node, attribute) for node in nodes]
            if any(value is None for value in values):
                return None
            return sum(float(value) * weight for value, weight in zip(values, weights, strict=True))

        def weighted_strike() -> float | None:
            values = [node.strike_degrees for node in nodes]
            if any(value is None for value in values):
                return None
            return circular_weighted_degrees(
                [float(value) for value in values],
                weights,
            )

        depth = weighted("depth_km")
        if depth is None:
            raise ValueError("Slab2 depth unexpectedly missing")
        return SlabSample(
            depth_km=depth,
            dip_degrees=weighted("dip_degrees"),
            strike_degrees=weighted_strike(),
            thickness_km=weighted("thickness_km"),
            uncertainty_km=weighted("uncertainty_km"),
            interpolation=interpolation,
            contributing_nodes=len(nodes),
        )
