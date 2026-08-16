import io
import math
import re
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import shapefile
from geoalchemy2 import Geography
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, func, insert, select
from sqlalchemy.orm import Session

from chile_oef.db.models import FaultTrace, TectonicRelease


@dataclass(frozen=True)
class FaultRecord:
    source_record_index: int
    external_id: str
    fault_system: str | None
    fault_name: str | None
    trace_name: str | None
    trace_type: str | None
    activity_class: str | None
    strike_degrees: float | None
    dip_degrees: float | None
    rake_degrees: float | None
    length_km: float | None
    geometry_wkt: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class NearestFault:
    trace_id: uuid.UUID
    external_id: str
    distance_km: float
    activity_class: str | None


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


_NUMBER_PATTERN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"


def _interpreted_float(value: Any) -> tuple[float | None, str]:
    if value is None or str(value).strip() == "":
        return None, "missing"
    text = str(value).strip()
    if re.fullmatch(_NUMBER_PATTERN, text):
        result = float(text)
        return (result, "exact") if math.isfinite(result) else (None, "non_finite")
    approximate = re.fullmatch(rf"~\s*({_NUMBER_PATTERN})", text)
    if approximate:
        return float(approximate.group(1)), "approximate"
    if "+/-" in text:
        return None, "central_value_with_uncertainty_unmodeled"
    if re.fullmatch(rf"{_NUMBER_PATTERN}\s*-\s*{_NUMBER_PATTERN}", text):
        return None, "range_unmodeled"
    return None, "qualitative_unmodeled"


def _multiline_wkt(shape: shapefile.Shape) -> str:
    if shape.shapeType not in (shapefile.POLYLINE, shapefile.POLYLINEM):
        raise ValueError(f"CHAF shape type {shape.shapeTypeName} is not a polyline")
    boundaries = list(shape.parts) + [len(shape.points)]
    lines: list[str] = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        points = shape.points[start:end]
        if len(points) < 2:
            raise ValueError("CHAF fault part has fewer than two points")
        lines.append(",".join(f"{longitude} {latitude}" for longitude, latitude in points))
    return "MULTILINESTRING(" + ",".join(f"({line})" for line in lines) + ")"


def iter_chaf_records(content: bytes) -> Iterator[FaultRecord]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = {name.lower(): name for name in archive.namelist()}

        def member(extension: str) -> bytes:
            matches = [original for lower, original in names.items() if lower.endswith(extension)]
            if len(matches) != 1:
                raise ValueError(f"CHAF archive has no unique {extension} member")
            return archive.read(matches[0])

        reader = shapefile.Reader(
            shp=io.BytesIO(member(".shp")),
            shx=io.BytesIO(member(".shx")),
            dbf=io.BytesIO(member(".dbf")),
            encoding="utf-8",
        )
        if reader.shapeType != shapefile.POLYLINE:
            raise ValueError(f"CHAF dataset shape type is {reader.shapeTypeName}")
        for source_record_index, shape_record in enumerate(
            reader.iterShapeRecords(),
            start=1,
        ):
            properties = {
                key: _json_value(value) for key, value in shape_record.record.as_dict().items()
            }
            interpreted = {
                field: _interpreted_float(properties.get(field))
                for field in ("strike", "dip", "rake", "length_km")
            }
            non_exact = {
                field: {"source_value": properties.get(field), "status": status}
                for field, (_, status) in interpreted.items()
                if status != "exact"
            }
            if non_exact:
                properties["_chile_oef_numeric_interpretation"] = non_exact
            yield FaultRecord(
                source_record_index=source_record_index,
                external_id=str(properties["F_id"]),
                fault_system=_optional_text(properties.get("F_system")),
                fault_name=_optional_text(properties.get("F_name")),
                trace_name=_optional_text(properties.get("FT_name")),
                trace_type=_optional_text(properties.get("type")),
                activity_class=_optional_text(properties.get("activity")),
                strike_degrees=interpreted["strike"][0],
                dip_degrees=interpreted["dip"][0],
                rake_degrees=interpreted["rake"][0],
                length_km=interpreted["length_km"][0],
                geometry_wkt=_multiline_wkt(shape_record.shape),
                properties=properties,
            )


class FaultService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def load_chaf(
        self,
        release: TectonicRelease,
        content: bytes,
        *,
        batch_size: int = 500,
    ) -> int:
        if release.status != "building":
            raise ValueError("CHAF can only be loaded into a building release")
        if release.source_id != "chaf_2020":
            raise ValueError("CHAF release has the wrong source")
        if (
            self.session.scalar(
                select(FaultTrace.id).where(FaultTrace.release_id == release.id).limit(1)
            )
            is not None
        ):
            raise ValueError("release already contains fault traces")
        count = 0
        batch: list[dict[str, object]] = []
        for fault in iter_chaf_records(content):
            batch.append(
                {
                    "id": uuid.uuid4(),
                    "release_id": release.id,
                    "source_record_index": fault.source_record_index,
                    "external_id": fault.external_id,
                    "fault_system": fault.fault_system,
                    "fault_name": fault.fault_name,
                    "trace_name": fault.trace_name,
                    "trace_type": fault.trace_type,
                    "activity_class": fault.activity_class,
                    "strike_degrees": fault.strike_degrees,
                    "dip_degrees": fault.dip_degrees,
                    "rake_degrees": fault.rake_degrees,
                    "length_km": fault.length_km,
                    "geometry": WKTElement(fault.geometry_wkt, srid=4326),
                    "properties_json": fault.properties,
                }
            )
            count += 1
            if len(batch) >= batch_size:
                self.session.execute(insert(FaultTrace), batch)
                batch.clear()
        if batch:
            self.session.execute(insert(FaultTrace), batch)
        release.status = "ready"
        release.metadata_json = {
            **release.metadata_json,
            "trace_count": count,
            "geometry_interpretation": "mapped_surface_trace_only",
        }
        self.session.commit()
        return count


class FaultRepository:
    def __init__(self, session: Session, release_id: uuid.UUID) -> None:
        self.session = session
        self.release_id = release_id

    def nearest(self, *, latitude: float, longitude: float) -> NearestFault | None:
        point = WKTElement(f"POINT({longitude} {latitude})", srid=4326)
        distance_m = func.ST_Distance(
            cast(point, Geography(geometry_type="POINT", srid=4326)),
            cast(FaultTrace.geometry, Geography(geometry_type="MULTILINESTRING", srid=4326)),
        )
        row = self.session.execute(
            select(FaultTrace, distance_m.label("distance_m"))
            .where(FaultTrace.release_id == self.release_id)
            .order_by(distance_m)
            .limit(1)
        ).first()
        if row is None:
            return None
        trace, distance = row
        return NearestFault(
            trace_id=trace.id,
            external_id=trace.external_id,
            distance_km=float(distance) / 1000.0,
            activity_class=trace.activity_class,
        )
