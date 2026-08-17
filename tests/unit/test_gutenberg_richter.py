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
    assert low_result.diagnostics["limited_dynamic_range"] is False
    assert low_result.diagnostics["unusual_b_value"] is False


# USGS ComCat mb histogram for Chile, 2005-01-01..2015-01-01, at/above the
# production Mc=4.97 (binned 5.0). Replicated 2026-08-16 from the live FDSN
# service; see research/b_value_mb_truncation.md. Not a synthetic GR catalog.
_PRODUCTION_MB_HISTOGRAM = {
    5.0: 200,
    5.1: 104,
    5.2: 75,
    5.3: 44,
    5.4: 21,
    5.5: 10,
    5.6: 13,
    5.7: 3,
    5.8: 4,
    5.9: 1,
    6.0: 6,
    6.1: 1,
    6.2: 1,
}


def test_production_mb_histogram_recovers_the_live_b_value_and_flags_truncation() -> None:
    magnitudes = [
        magnitude for magnitude, count in _PRODUCTION_MB_HISTOGRAM.items() for _ in range(count)
    ]
    result = estimate_b_value(magnitudes, mc=4.97)
    assert result.events_at_or_above_mc == 483
    assert result.b_value == pytest.approx(2.131, abs=0.001)
    assert result.b_value_standard_error == pytest.approx(0.098, abs=0.001)
    assert result.diagnostics["max_magnitude_at_or_above_mc"] == pytest.approx(6.2)
    assert result.diagnostics["magnitude_range_above_mc"] == pytest.approx(1.2)
    assert result.diagnostics["limited_dynamic_range"] is True
    assert result.diagnostics["unusual_b_value"] is True
