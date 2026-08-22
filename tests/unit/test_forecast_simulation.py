import math

import pytest

from chile_oef.forecast.simulation import (
    CatalogSimulationPolicy,
    simulate_predictive_catalog_counts,
)
from chile_oef.forecast.specification import MagnitudeBin
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasParameters


def _parameters(*, mu: float, k0: float) -> SpatiotemporalEtasParameters:
    return SpatiotemporalEtasParameters(
        mu_per_day=mu,
        k0=k0,
        alpha=0.5,
        c_days=0.1,
        p_exponent=1.2,
        d0_km=5.0,
        gamma=0.0,
        q_exponent=1.8,
    )


def test_background_only_simulation_recovers_poisson_distribution() -> None:
    expected = 2.0
    result = simulate_predictive_catalog_counts(
        prior_event_times_days=[],
        prior_event_magnitudes=[],
        etas_parameters=_parameters(mu=expected, k0=0.0),
        b_value=1.0,
        reference_magnitude=3.0,
        validity_start_days=10.0,
        validity_end_days=11.0,
        magnitude_bins=(MagnitudeBin(lower=3.0, upper=None),),
        policy=CatalogSimulationPolicy(simulations=20_000, seed=7),
    )
    assert result.total_count.mean == pytest.approx(expected, abs=0.04)
    assert result.total_count.probability_at_least_one == pytest.approx(
        1.0 - math.exp(-expected), abs=0.01
    )
    assert result.magnitude_bins[0]["mean"] == pytest.approx(result.total_count.mean)


def test_simulation_includes_future_secondary_triggering_and_is_reproducible() -> None:
    kwargs = dict(
        prior_event_times_days=[9.9],
        prior_event_magnitudes=[5.0],
        etas_parameters=_parameters(mu=0.0, k0=0.3),
        b_value=1.0,
        reference_magnitude=3.0,
        validity_start_days=10.0,
        validity_end_days=11.0,
        magnitude_bins=(MagnitudeBin(lower=3.0, upper=None),),
        policy=CatalogSimulationPolicy(simulations=2_000, seed=9),
    )
    first = simulate_predictive_catalog_counts(**kwargs)
    second = simulate_predictive_catalog_counts(**kwargs)
    assert first == second
    assert first.total_count.mean is not None
    assert first.total_count.mean > 1.0
    assert first.total_count.p95 is not None
    assert first.total_count.p95 > first.total_count.mean
    assert first.diagnostics["aleatory_branching_uncertainty"] is True
    assert first.diagnostics["parameter_uncertainty"] is False


def test_simulation_refuses_to_report_bins_below_completeness() -> None:
    result = simulate_predictive_catalog_counts(
        prior_event_times_days=[],
        prior_event_magnitudes=[],
        etas_parameters=_parameters(mu=1.0, k0=0.0),
        b_value=1.0,
        reference_magnitude=4.0,
        validity_start_days=0.0,
        validity_end_days=1.0,
        magnitude_bins=(
            MagnitudeBin(lower=3.0, upper=4.0),
            MagnitudeBin(lower=4.0, upper=None),
        ),
        policy=CatalogSimulationPolicy(simulations=100, seed=3),
    )
    assert result.magnitude_bins[0]["support_state"] == "not_estimable"
    assert result.magnitude_bins[0]["probability_at_least_one"] is None
    assert result.magnitude_bins[1]["support_state"] == "estimable"
