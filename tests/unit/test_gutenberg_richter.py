import pytest

from chile_oef.seismicity.gutenberg_richter import estimate_b_value


def _exact_gr_magnitudes(
    *, mc_true: float, b_value: float, n0: int, bin_width: float, top_magnitude: float
) -> list[float]:
    bin_count = round((top_magnitude - mc_true) / bin_width) + 1
    bins = [round(mc_true + index * bin_width, 10) for index in range(bin_count)]
    cumulative = {
        bin_value: round(n0 * 10 ** (-b_value * (bin_value - mc_true))) for bin_value in bins
    }
    noncumulative = {
        bin_value: (
            cumulative[bin_value] - cumulative[bins[index + 1]]
            if index + 1 < len(bins)
            else cumulative[bin_value]
        )
        for index, bin_value in enumerate(bins)
    }
    magnitudes: list[float] = []
    for bin_value, count in noncumulative.items():
        magnitudes.extend([bin_value] * count)
    return magnitudes


def test_below_minimum_sample_at_or_above_mc_is_not_estimable() -> None:
    result = estimate_b_value([3.0] * 10, mc=3.0)
    assert result.support_state == "not_estimable"
    assert result.b_value is None
    assert result.b_value_standard_error is None
    assert result.a_value is None
    assert result.events_at_or_above_mc == 10


def test_only_events_at_or_above_mc_count_toward_the_sample() -> None:
    below = [2.5] * 500  # far more than enough events, but all under Mc
    above = [3.0] * 60
    result = estimate_b_value(below + above, mc=3.0)
    assert result.event_count == 560
    assert result.events_at_or_above_mc == 60
    assert result.support_state == "research_only"


def test_regression_fixture_recovers_exact_gr_b_value() -> None:
    magnitudes = _exact_gr_magnitudes(
        mc_true=3.0, b_value=1.0, n0=1000, bin_width=0.1, top_magnitude=6.0
    )
    result = estimate_b_value(magnitudes, mc=3.0)
    assert result.event_count == len(magnitudes)
    assert result.events_at_or_above_mc == len(magnitudes)
    assert result.support_state == "supported"
    assert result.b_value == pytest.approx(1.0, abs=0.01)
    assert result.b_value_standard_error is not None
    assert result.b_value_standard_error > 0
    assert result.method_version == "gutenberg_richter_aki_mle_v1"
    assert result.calibration_status == "uncalibrated_mle_estimator"
    # a-value must reproduce the observed count at Mc exactly (by construction
    # of the MLE anchoring), not just approximately.
    predicted_count_at_mc = 10 ** (result.a_value - result.b_value * 3.0)
    assert predicted_count_at_mc == pytest.approx(result.events_at_or_above_mc, rel=1e-6)


def test_higher_b_value_catalog_recovers_higher_b_value() -> None:
    low_b = _exact_gr_magnitudes(
        mc_true=3.0, b_value=0.8, n0=1000, bin_width=0.1, top_magnitude=6.0
    )
    high_b = _exact_gr_magnitudes(
        mc_true=3.0, b_value=1.3, n0=1000, bin_width=0.1, top_magnitude=6.0
    )
    low_result = estimate_b_value(low_b, mc=3.0)
    high_result = estimate_b_value(high_b, mc=3.0)
    assert low_result.b_value == pytest.approx(0.8, abs=0.02)
    assert high_result.b_value == pytest.approx(1.3, abs=0.02)
    assert low_result.b_value < high_result.b_value
