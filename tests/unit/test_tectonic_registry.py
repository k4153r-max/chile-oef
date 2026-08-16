import json
from pathlib import Path

from jsonschema import Draft202012Validator

from chile_oef.tectonics.registry import load_tectonic_registry


def test_pinned_tectonic_registry_has_unique_verified_assets() -> None:
    registry = load_tectonic_registry(Path("config/tectonic-assets.yaml"))
    assert {release.id for release in registry.releases} == {
        "slab2_south_america_2018",
        "chaf_2020",
    }
    schema = json.loads(Path("schemas/tectonic-asset-manifest.schema.json").read_text())
    validator = Draft202012Validator(schema)
    for release in registry.releases:
        asset_types = [asset.type for asset in release.assets]
        assert len(asset_types) == len(set(asset_types))
        assert not list(validator.iter_errors(release.model_dump(mode="json")))

    slab = registry.by_id("slab2_south_america_2018")
    assert {asset.type for asset in slab.assets} == {
        "depth",
        "dip",
        "strike",
        "thickness",
        "uncertainty",
    }
    chaf = registry.by_id("chaf_2020")
    assert chaf.license == "CC-BY-4.0"
    assert chaf.asset("faults_shapefile").url.startswith("https://download.pangaea.de/")
