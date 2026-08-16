from datetime import UTC, datetime

import pytest

from chile_oef.ingestion.sources.usgs_fdsn import UsgsFdsnAdapter


def _adapter() -> UsgsFdsnAdapter:
    return UsgsFdsnAdapter(
        start_time=datetime(2026, 8, 1, tzinfo=UTC),
        end_time=datetime(2026, 8, 2, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [("2\n", 2), ('{"count":2,"maxAllowed":20000}', 2)],
)
def test_count_parser_accepts_service_response_forms(payload: str, expected: int) -> None:
    assert _adapter().parse_count_response(payload) == expected


def test_count_parser_rejects_malformed_json() -> None:
    with pytest.raises(ValueError, match="integer count"):
        _adapter().parse_count_response('{"maxAllowed":20000}')


def test_fdsn_query_is_bounded_to_chile_margin() -> None:
    parameters = _adapter().query_parameters(format_name="geojson")

    assert parameters["minlatitude"] == -60
    assert parameters["maxlatitude"] == -15
    assert parameters["minlongitude"] == -82
    assert parameters["maxlongitude"] == -62
