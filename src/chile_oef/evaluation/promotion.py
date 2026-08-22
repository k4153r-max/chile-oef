"""Deterministic, auditable promotion gate for evaluated forecast models."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
from numpy.random import Generator

PromotionState = Literal["promote", "retain_champion", "insufficient_evidence"]


@dataclass(frozen=True)
class PromotionPolicy:
    """Conservative research defaults; changing them creates a new method version."""

    min_folds: int = 20
    min_observed_events: int = 20
    min_estimable_csep_folds: int = 10
    min_information_gain_lower: float = 0.0
    target_predictive_coverage: float = 0.90
    predictive_coverage_tolerance: float = 0.10
    max_reliability_ece_upper: float = 0.10
    min_csep_consistent_fraction: float = 0.80
    method_version: str = "promotion_gate_v1"

    def __post_init__(self) -> None:
        if self.min_folds < 2 or self.min_observed_events < 1:
            raise ValueError("promotion evidence minima must be positive")
        if self.min_estimable_csep_folds < 1:
            raise ValueError("min_estimable_csep_folds must be positive")
        for value in (
            self.target_predictive_coverage,
            self.predictive_coverage_tolerance,
            self.max_reliability_ece_upper,
            self.min_csep_consistent_fraction,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("probability thresholds must be between zero and one")


@dataclass(frozen=True)
class PromotionAssessment:
    state: PromotionState
    checks: dict[str, dict[str, Any]]
    reasons: tuple[str, ...]
    policy: PromotionPolicy

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "checks": self.checks,
            "reasons": list(self.reasons),
            "policy": asdict(self.policy),
        }


def assess_model_promotion(
    *,
    aggregate_scores: Mapping[str, Any],
    comparative_information_gain: Mapping[str, Any] | None,
    fold_count: int,
    observed_event_count: int,
    policy: PromotionPolicy | None = None,
) -> PromotionAssessment:
    """Assess an immutable walk-forward run without modifying model state.

    ``comparative_information_gain`` must be a paired block-bootstrap comparison
    against the actual registered champion, not merely a generic reference.
    The gate deliberately treats missing evidence as insufficient rather than
    silently promoting or rejecting a model.
    """
    policy = policy or PromotionPolicy()
    checks: dict[str, dict[str, Any]] = {}
    insufficient_reasons: list[str] = []
    quality_reasons: list[str] = []

    def evidence_check(name: str, observed: Any, required: str, passed: bool) -> None:
        checks[name] = {"observed": observed, "required": required, "passed": passed}
        if not passed:
            insufficient_reasons.append(f"{name}: evidencia insuficiente")

    evidence_check(
        "fold_count", fold_count, f">= {policy.min_folds}", fold_count >= policy.min_folds
    )
    evidence_check(
        "observed_event_count",
        observed_event_count,
        f">= {policy.min_observed_events}",
        observed_event_count >= policy.min_observed_events,
    )

    required_bootstraps = {
        "predictive_coverage": "point_estimate",
        "reliability_expected_calibration_error": "upper",
    }
    bootstraps: dict[str, Mapping[str, Any]] = {}
    for name, field in required_bootstraps.items():
        value = aggregate_scores.get(name)
        valid = isinstance(value, Mapping) and isinstance(value.get(field), (int, float))
        evidence_check(f"{name}_available", value is not None, f"bootstrap with {field}", valid)
        if valid:
            bootstraps[name] = value
    comparison_valid = isinstance(comparative_information_gain, Mapping) and isinstance(
        comparative_information_gain.get("lower"), (int, float)
    )
    evidence_check(
        "comparative_information_gain_available",
        comparative_information_gain is not None,
        "paired champion comparison with lower confidence bound",
        comparison_valid,
    )

    csep_names = ("number_test", "likelihood_test", "spatial_test", "magnitude_test")
    csep: dict[str, Mapping[str, Any]] = {}
    for name in csep_names:
        value = aggregate_scores.get(name)
        fold_key = "fold_count" if name == "number_test" else "fold_count_estimable"
        fold_value = value.get(fold_key) if isinstance(value, Mapping) else None
        fraction = value.get("fraction_consistent_at_alpha") if isinstance(value, Mapping) else None
        valid = (
            isinstance(fold_value, int)
            and fold_value >= policy.min_estimable_csep_folds
            and isinstance(fraction, (int, float))
        )
        evidence_check(
            f"{name}_estimable",
            fold_value,
            f">= {policy.min_estimable_csep_folds} estimable folds",
            valid,
        )
        if valid:
            csep[name] = value

    if insufficient_reasons:
        return PromotionAssessment(
            state="insufficient_evidence",
            checks=checks,
            reasons=tuple(insufficient_reasons),
            policy=policy,
        )

    def quality_check(name: str, observed: float, required: str, passed: bool) -> None:
        checks[name] = {"observed": observed, "required": required, "passed": passed}
        if not passed:
            quality_reasons.append(f"{name}: no cumple el umbral")

    assert comparative_information_gain is not None
    information_gain_lower = float(comparative_information_gain["lower"])
    quality_check(
        "information_gain_lower",
        information_gain_lower,
        f"> {policy.min_information_gain_lower}",
        information_gain_lower > policy.min_information_gain_lower,
    )
    coverage = float(bootstraps["predictive_coverage"]["point_estimate"])
    coverage_delta = abs(coverage - policy.target_predictive_coverage)
    quality_check(
        "predictive_coverage_error",
        coverage_delta,
        f"<= {policy.predictive_coverage_tolerance}",
        coverage_delta <= policy.predictive_coverage_tolerance,
    )
    ece_upper = float(bootstraps["reliability_expected_calibration_error"]["upper"])
    quality_check(
        "reliability_ece_upper",
        ece_upper,
        f"<= {policy.max_reliability_ece_upper}",
        ece_upper <= policy.max_reliability_ece_upper,
    )
    for name, value in csep.items():
        fraction = float(value["fraction_consistent_at_alpha"])
        quality_check(
            f"{name}_consistent_fraction",
            fraction,
            f">= {policy.min_csep_consistent_fraction}",
            fraction >= policy.min_csep_consistent_fraction,
        )

    state: PromotionState = "retain_champion" if quality_reasons else "promote"
    reasons = tuple(quality_reasons) or ("todos los criterios de promoción se cumplen",)
    return PromotionAssessment(state=state, checks=checks, reasons=reasons, policy=policy)


def paired_information_gain_bootstrap(
    *,
    candidate_log_likelihoods: list[float],
    champion_log_likelihoods: list[float],
    observed_event_counts: list[int],
    rng: Generator,
    n_resamples: int = 2000,
    confidence_level: float = 0.90,
) -> dict[str, float | int] | None:
    """Paired time-block bootstrap of candidate gain per observed event."""
    fold_count = len(candidate_log_likelihoods)
    if fold_count != len(champion_log_likelihoods) or fold_count != len(observed_event_counts):
        raise ValueError("candidate, champion, and observation arrays must align")
    if fold_count < 2:
        return None
    if n_resamples < 1 or not 0.0 < confidence_level < 1.0:
        raise ValueError("invalid bootstrap policy")
    if any(count < 0 for count in observed_event_counts):
        raise ValueError("observed event counts cannot be negative")

    candidate = np.asarray(candidate_log_likelihoods, dtype=float)
    champion = np.asarray(champion_log_likelihoods, dtype=float)
    observed = np.asarray(observed_event_counts, dtype=float)
    if not np.all(np.isfinite(candidate)) or not np.all(np.isfinite(champion)):
        raise ValueError("log likelihoods must be finite")
    total_observed = int(observed.sum())
    if total_observed == 0:
        return None

    differences = candidate - champion
    indices = rng.integers(0, fold_count, size=(n_resamples, fold_count))
    denominators = observed[indices].sum(axis=1)
    numerators = differences[indices].sum(axis=1)
    estimable = numerators[denominators > 0] / denominators[denominators > 0]
    if estimable.size == 0:
        return None
    alpha = 1.0 - confidence_level
    return {
        "point_estimate": float(differences.sum() / total_observed),
        "lower": float(np.percentile(estimable, 100.0 * alpha / 2.0)),
        "upper": float(np.percentile(estimable, 100.0 * (1.0 - alpha / 2.0))),
        "confidence_level": confidence_level,
        "paired_fold_count": fold_count,
        "observed_event_count": total_observed,
        "bootstrap_resamples_estimable": int(estimable.size),
    }
