import math

import numpy as np
import pytest

from chile_oef.evaluation.scoring import (
    average_precision,
    binary_log_loss,
    brier_score,
    information_gain_per_event,
    poisson_deviance,
    poisson_log_likelihood,
    predictive_coverage,
    reliability_curve,
    roc_auc,
    threshold_scores,
)


def test_log_loss_hand_computed() -> None:
    observed = [1, 0]
    predicted = [0.8, 0.3]
    expected = -(math.log(0.8) + math.log(0.7)) / 2.0
    assert binary_log_loss(observed, predicted) == pytest.approx(expected)


def test_brier_hand_computed() -> None:
    observed = [1, 0]
    predicted = [0.8, 0.3]
    expected = ((0.8 - 1.0) ** 2 + (0.3 - 0.0) ** 2) / 2.0
    assert brier_score(observed, predicted) == pytest.approx(expected)


def test_log_loss_and_brier_are_near_zero_for_a_near_perfect_forecast() -> None:
    observed = [1, 0, 1, 0]
    predicted = [0.999999, 0.000001, 0.999999, 0.000001]
    assert binary_log_loss(observed, predicted) < 1e-4
    assert brier_score(observed, predicted) < 1e-6


def test_reliability_curve_is_perfectly_calibrated_by_construction() -> None:
    predicted = [0.1] * 10 + [0.9] * 10
    observed = [1] + [0] * 9 + [1] * 9 + [0]
    result = reliability_curve(observed, predicted, bin_count=2)
    assert result.expected_calibration_error == pytest.approx(0.0, abs=1e-12)
    assert len(result.bins) == 2


def test_reliability_curve_detects_miscalibration() -> None:
    predicted = [0.9] * 20
    observed = [0] * 20
    result = reliability_curve(observed, predicted, bin_count=1)
    assert result.expected_calibration_error == pytest.approx(0.9)


def test_threshold_scores_hand_computed_confusion_matrix() -> None:
    observed = [1, 1, 0, 0]
    predicted = [0.9, 0.4, 0.6, 0.1]
    result = threshold_scores(observed, predicted, threshold=0.5)
    # alarms: index 0 (p=0.9, y=1 -> TP), index 2 (p=0.6, y=0 -> FP)
    # no-alarms: index 1 (p=0.4, y=1 -> FN), index 3 (p=0.1, y=0 -> TN)
    assert result.precision == pytest.approx(0.5)
    assert result.recall == pytest.approx(0.5)
    assert result.false_alarm_rate == pytest.approx(0.5)
    assert result.f1 == pytest.approx(0.5)


def test_threshold_scores_undefined_when_no_positives_at_all() -> None:
    result = threshold_scores([0, 0, 0], [0.9, 0.1, 0.2], threshold=0.5)
    assert result.recall is None
    assert result.precision == pytest.approx(0.0)  # one alarm, zero true positives


def test_average_precision_perfect_ranking_is_one() -> None:
    observed = [0, 0, 1, 1]
    predicted = [0.1, 0.2, 0.8, 0.9]
    assert average_precision(observed, predicted) == pytest.approx(1.0)


def test_average_precision_no_positives_returns_none() -> None:
    assert average_precision([0, 0, 0], [0.1, 0.5, 0.9]) is None


def _brute_force_auc(observed: list[int], predicted: list[float]) -> float:
    """Independent re-derivation: ROC-AUC as the fraction of (positive,
    negative) pairs correctly ranked, ties counted as half a win -- the
    textbook probabilistic definition, computed without any ranking
    machinery, to check roc_auc()'s rank-based implementation.
    """
    positives = [p for y, p in zip(observed, predicted, strict=True) if y == 1]
    negatives = [p for y, p in zip(observed, predicted, strict=True) if y == 0]
    total = 0.0
    for p_pos in positives:
        for p_neg in negatives:
            if p_pos > p_neg:
                total += 1.0
            elif p_pos == p_neg:
                total += 0.5
    return total / (len(positives) * len(negatives))


def test_roc_auc_matches_brute_force_pair_counting_with_ties() -> None:
    observed = [1, 0, 1, 0, 1]
    predicted = [0.7, 0.7, 0.9, 0.2, 0.5]
    assert roc_auc(observed, predicted) == pytest.approx(_brute_force_auc(observed, predicted))


def test_roc_auc_undefined_without_both_classes() -> None:
    assert roc_auc([1, 1, 1], [0.2, 0.5, 0.9]) is None
    assert roc_auc([0, 0, 0], [0.2, 0.5, 0.9]) is None


def test_poisson_log_likelihood_hand_computed() -> None:
    observed = [2]
    rates = [3.0]
    expected = 2 * math.log(3.0) - 3.0 - math.lgamma(3.0)
    assert poisson_log_likelihood(observed, rates) == pytest.approx(expected)


def test_poisson_deviance_is_zero_when_observed_equals_forecast_exactly() -> None:
    assert poisson_deviance([2.0, 5.0, 0.0], [2.0, 5.0, 1e-9]) == pytest.approx(0.0, abs=1e-6)


def test_poisson_deviance_hand_computed_nonzero_case() -> None:
    observed = [4.0]
    rates = [2.0]
    expected = 2.0 * (4.0 * math.log(4.0 / 2.0) - (4.0 - 2.0))
    assert poisson_deviance(observed, rates) == pytest.approx(expected)


def test_predictive_coverage_matches_its_own_nominal_level_under_simulation() -> None:
    """Independent check: simulate many (rate, observed-count) pairs by
    actually drawing observed ~ Poisson(rate), then verify the fraction
    predictive_coverage() reports as 'covered' converges to at least the
    requested coverage level. Discrete equal-tailed intervals cannot hit
    an exact tail probability (the CDF is a step function), so they are
    conservative -- true coverage is >= nominal, not equal to it, most
    visibly at the small rates in this mix (rates as low as 0.5). Coverage
    below 0.90 would be a real bug; coverage moderately above 0.90 is the
    expected, correct behavior for discrete intervals.
    """
    rng = np.random.default_rng(42)
    rates = rng.uniform(0.5, 20.0, size=5000)
    observed = rng.poisson(rates)
    coverage = predictive_coverage(observed, rates, coverage_level=0.90)
    assert 0.90 <= coverage <= 0.97


def test_information_gain_per_event_zero_observed_returns_none() -> None:
    assert information_gain_per_event([0, 0], [1.0, 1.0], [0.5, 0.5]) is None


def test_information_gain_per_event_positive_when_model_matches_observed_better() -> None:
    observed = [5, 0]
    good_model = [5.0, 0.01]
    bad_reference = [2.5, 2.5]
    gain = information_gain_per_event(observed, good_model, bad_reference)
    assert gain is not None
    assert gain > 0.0
