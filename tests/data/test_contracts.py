import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from chile_oef.ingestion.registry import load_source_registry


def test_all_json_schemas_are_valid() -> None:
    for path in Path("schemas").glob("*.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_source_registry_is_typed_and_has_no_invented_csn_event_api() -> None:
    registry = load_source_registry(Path("config/source-registry.yaml"))
    assert registry.by_id("usgs_comcat").enabled is True
    csn = registry.by_id("csn_daily")
    assert csn.enabled is False
    assert {endpoint.kind for endpoint in csn.endpoints} == {"html_daily"}


def test_forecast_spec_has_coherent_horizons_and_bins() -> None:
    document = yaml.safe_load(Path("config/forecast-specification.yaml").read_text())
    seconds = [item["seconds"] for item in document["horizons"]]
    assert seconds == sorted(seconds)
    bins = document["magnitude_bins"]
    assert [item["lower"] for item in bins] == sorted(item["lower"] for item in bins)
    assert document["estimability"]["reject_threshold_below_mc"] is True
