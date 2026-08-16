import io
import zipfile

import shapefile

from chile_oef.tectonics.faults import iter_chaf_records


def _fixture_chaf_zip() -> bytes:
    shp = io.BytesIO()
    shx = io.BytesIO()
    dbf = io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYLINE) as writer:
        writer.field("F_id", "C", size=12)
        writer.field("F_system", "C", size=40)
        writer.field("F_name", "C", size=40)
        writer.field("FT_name", "C", size=40)
        writer.field("type", "C", size=20)
        writer.field("activity", "C", size=20)
        writer.field("strike", "F", size=8, decimal=2)
        writer.field("dip", "C", size=20)
        writer.field("rake", "C", size=20)
        writer.field("length_km", "F", size=8, decimal=2)
        writer.line([[[-72.1, -33.1], [-71.9, -32.9]]])
        writer.record(
            "F001",
            "Central",
            "Fixture",
            "Trace 1",
            "reverse",
            "active",
            5,
            "~90",
            "-165 +/- 15",
            12,
        )
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("fixture.shp", shp.getvalue())
        archive.writestr("fixture.shx", shx.getvalue())
        archive.writestr("fixture.dbf", dbf.getvalue())
    return archive_buffer.getvalue()


def test_chaf_parser_preserves_source_fields_and_multiline_geometry() -> None:
    records = list(iter_chaf_records(_fixture_chaf_zip()))
    assert len(records) == 1
    record = records[0]
    assert record.source_record_index == 1
    assert record.external_id == "F001"
    assert record.activity_class == "active"
    assert record.dip_degrees == 90.0
    assert record.rake_degrees is None
    interpretation = record.properties["_chile_oef_numeric_interpretation"]
    assert interpretation["dip"]["status"] == "approximate"
    assert interpretation["rake"]["status"] == "central_value_with_uncertainty_unmodeled"
    assert record.geometry_wkt.startswith("MULTILINESTRING(")
