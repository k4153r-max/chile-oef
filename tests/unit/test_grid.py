from decimal import Decimal

import pytest

from chile_oef.tectonics.grid import GridDefinition, iter_cells


def test_grid_is_deterministic_and_uses_nonzero_spherical_areas() -> None:
    definition = GridDefinition(
        id="fixture_0_1_v1",
        resolution_degrees=Decimal("0.1"),
        min_latitude=Decimal("-33.2"),
        max_latitude=Decimal("-33.0"),
        min_longitude=Decimal("-72.2"),
        max_longitude=Decimal("-72.0"),
    )
    cells = list(iter_cells(definition))
    assert definition.cell_count == 4
    assert [cell.id for cell in cells] == [
        "fixture_0_1_v1:r0000:c0000",
        "fixture_0_1_v1:r0000:c0001",
        "fixture_0_1_v1:r0001:c0000",
        "fixture_0_1_v1:r0001:c0001",
    ]
    assert all(cell.area_km2 > 0 for cell in cells)
    assert definition.digest == definition.digest


def test_grid_rejects_fractional_step_count() -> None:
    definition = GridDefinition(
        id="invalid",
        resolution_degrees=Decimal("0.2"),
        min_latitude=Decimal("-33.1"),
        max_latitude=Decimal("-33.0"),
        min_longitude=Decimal("-72.2"),
        max_longitude=Decimal("-72.0"),
    )
    with pytest.raises(ValueError, match="latitude span"):
        definition.validate()
