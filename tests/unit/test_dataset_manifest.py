from chile_oef.datasets.service import manifest_digest


def test_manifest_digest_is_independent_of_mapping_order() -> None:
    left = {"dataset_id": "catalog", "version": "v1", "sources": ["csn", "usgs"]}
    right = {"sources": ["csn", "usgs"], "version": "v1", "dataset_id": "catalog"}

    assert manifest_digest(left) == manifest_digest(right)


def test_manifest_digest_changes_with_scientific_selection() -> None:
    left = {"as_of": "2010-02-27T02:59:59Z", "event_revisions": ["revision-a"]}
    right = {"as_of": "2010-02-27T02:59:59Z", "event_revisions": ["revision-b"]}

    assert manifest_digest(left) != manifest_digest(right)
