import numpy as np
import pytest

from chile_oef.evaluation.promotion import (
    PromotionPolicy,
    assess_model_promotion,
    paired_information_gain_bootstrap,
)


def _passing_aggregates() -> dict[str, object]:
    return {
        "predictive_coverage": {"point_estimate": 0.88},
        "reliability_expected_calibration_error": {"upper": 0.07},
        "number_test": {"fold_count": 30, "fraction_consistent_at_alpha": 0.90},
        "likelihood_test": {
            "fold_count_estimable": 30,
            "fraction_consistent_at_alpha": 0.90,
        },
        "spatial_test": {"fold_count_estimable": 25, "fraction_consistent_at_alpha": 0.84},
        "magnitude_test": {"fold_count_estimable": 25, "fraction_consistent_at_alpha": 0.88},
    }


def test_promotes_only_when_all_registered_checks_pass() -> None:
    result = assess_model_promotion(
        aggregate_scores=_passing_aggregates(),
        comparative_information_gain={"lower": 0.05},
        fold_count=30,
        observed_event_count=40,
    )

    assert result.state == "promote"
    assert result.checks["information_gain_lower"]["passed"] is True


def test_retains_champion_when_improvement_is_not_statistically_positive() -> None:
    result = assess_model_promotion(
        aggregate_scores=_passing_aggregates(),
        comparative_information_gain={"lower": -0.01},
        fold_count=30,
        observed_event_count=40,
    )

    assert result.state == "retain_champion"
    assert result.checks["information_gain_lower"]["passed"] is False


def test_missing_or_sparse_csep_evidence_never_rejects_or_promotes() -> None:
    aggregates = _passing_aggregates()
    aggregates["spatial_test"] = {
        "fold_count_estimable": 2,
        "fraction_consistent_at_alpha": 1.0,
    }

    result = assess_model_promotion(
        aggregate_scores=aggregates,
        comparative_information_gain={"lower": 0.05},
        fold_count=30,
        observed_event_count=40,
        policy=PromotionPolicy(min_estimable_csep_folds=10),
    )

    assert result.state == "insufficient_evidence"
    assert result.checks["spatial_test_estimable"]["passed"] is False


def test_paired_bootstrap_compares_candidate_with_actual_champion() -> None:
    result = paired_information_gain_bootstrap(
        candidate_log_likelihoods=[-8.0, -7.0, -6.0],
        champion_log_likelihoods=[-9.0, -8.0, -7.0],
        observed_event_counts=[2, 1, 2],
        rng=np.random.default_rng(7),
        n_resamples=500,
    )

    assert result is not None
    assert result["point_estimate"] == pytest.approx(0.6)
    assert result["lower"] > 0.0
