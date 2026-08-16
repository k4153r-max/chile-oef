"""Pure scoring functions for the score names registered in
config/evaluation-protocol.yaml: binary (log_loss, brier_score,
reliability), count (point_process_log_likelihood, deviance,
predictive_coverage), spatial (information_gain_per_event), rare-event
(pr_auc, recall, false_alarm_rate) and secondary (roc_auc, precision, f1)
scores. `accuracy` is the protocol's one explicitly prohibited primary
score and is deliberately never computed here.

Every function returns `None` (not a fabricated number) when the inputs
make the score mathematically undefined -- no positives for recall/pr_auc,
no negatives for roc_auc/false_alarm_rate, zero observed events for
information gain per event -- the same refuse-rather-than-guess discipline
`not_estimable` uses everywhere else in this project.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats

_LOG_EPS = 1e-12
_RATE_FLOOR = 1e-12


def binary_log_loss(observed: Sequence[int], predicted_probability: Sequence[float]) -> float:
    """Mean binary cross-entropy. Probabilities are clipped to
    [_LOG_EPS, 1 - _LOG_EPS] only so log() stays finite -- this is a
    numerical-stability floor, not a claim that a forecast probability of
    exactly 0 or 1 is plausible.
    """
    y = np.asarray(observed, dtype=float)
    p = np.clip(np.asarray(predicted_probability, dtype=float), _LOG_EPS, 1.0 - _LOG_EPS)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def brier_score(observed: Sequence[int], predicted_probability: Sequence[float]) -> float:
    y = np.asarray(observed, dtype=float)
    p = np.asarray(predicted_probability, dtype=float)
    return float(np.mean((p - y) ** 2))


@dataclass(frozen=True)
class ReliabilityBin:
    predicted_probability_mean: float
    observed_frequency: float
    count: int


@dataclass(frozen=True)
class ReliabilityResult:
    bins: tuple[ReliabilityBin, ...]
    expected_calibration_error: float


def reliability_curve(
    observed: Sequence[int], predicted_probability: Sequence[float], *, bin_count: int = 10
) -> ReliabilityResult:
    """Calibration curve binned by predicted-probability quantile, not
    equal width. Per-cell/per-magnitude-bin earthquake probabilities are
    extremely right-skewed (typically 1e-6 to 1e-2); equal-width bins over
    [0, 1] would put almost every point in the first bin and leave the
    rest empty. Quantile bins keep every bin populated.
    """
    y = np.asarray(observed, dtype=float)
    p = np.asarray(predicted_probability, dtype=float)
    n = len(p)
    order = np.argsort(p)
    edges = np.linspace(0, n, bin_count + 1, dtype=int)
    bins: list[ReliabilityBin] = []
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        if hi <= lo:
            continue
        idx = order[lo:hi]
        mean_p = float(np.mean(p[idx]))
        mean_y = float(np.mean(y[idx]))
        bins.append(ReliabilityBin(mean_p, mean_y, len(idx)))
        ece += (len(idx) / n) * abs(mean_p - mean_y)
    return ReliabilityResult(bins=tuple(bins), expected_calibration_error=ece)


@dataclass(frozen=True)
class ThresholdScores:
    threshold: float
    precision: float | None
    recall: float | None
    false_alarm_rate: float | None
    f1: float | None


def threshold_scores(
    observed: Sequence[int], predicted_probability: Sequence[float], *, threshold: float
) -> ThresholdScores:
    """Precision/recall/false-alarm-rate/f1 at one declared decision
    threshold. There is no registered default threshold in
    config/evaluation-protocol.yaml -- the caller must supply one
    deliberately rather than this function silently picking 0.5, which
    would almost never fire for genuinely rare per-cell earthquake
    probabilities.
    """
    y = np.asarray(observed, dtype=float)
    alarm = np.asarray(predicted_probability, dtype=float) >= threshold
    tp = float(np.sum(alarm & (y == 1)))
    fp = float(np.sum(alarm & (y == 0)))
    fn = float(np.sum(~alarm & (y == 1)))
    tn = float(np.sum(~alarm & (y == 0)))
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    false_alarm_rate = fp / (fp + tn) if (fp + tn) > 0 else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall) > 0
        else None
    )
    return ThresholdScores(threshold, precision, recall, false_alarm_rate, f1)


def average_precision(
    observed: Sequence[int], predicted_probability: Sequence[float]
) -> float | None:
    """`pr_auc` in config/evaluation-protocol.yaml, computed as average
    precision (precision-weighted recall steps over score-sorted data) --
    threshold-free and well-defined without interpolation ambiguity.
    `None` when there are no positives (undefined).
    """
    y = np.asarray(observed, dtype=float)
    p = np.asarray(predicted_probability, dtype=float)
    n_pos = float(np.sum(y == 1))
    if n_pos == 0:
        return None
    order = np.argsort(-p, kind="stable")
    y_sorted = y[order]
    tp_cumulative = np.cumsum(y_sorted)
    counts = np.arange(1, len(y_sorted) + 1)
    precision_at_k = tp_cumulative / counts
    recall_at_k = tp_cumulative / n_pos
    recall_prev = np.concatenate(([0.0], recall_at_k[:-1]))
    return float(np.sum((recall_at_k - recall_prev) * precision_at_k))


def roc_auc(observed: Sequence[int], predicted_probability: Sequence[float]) -> float | None:
    """Rank-based ROC-AUC (Mann-Whitney U), correct under tied scores via
    average ranks. `None` when there are no positives or no negatives.
    """
    y = np.asarray(observed, dtype=float)
    p = np.asarray(predicted_probability, dtype=float)
    n_pos = float(np.sum(y == 1))
    n_neg = float(np.sum(y == 0))
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = stats.rankdata(p)
    sum_ranks_pos = float(np.sum(ranks[y == 1]))
    u_statistic = sum_ranks_pos - n_pos * (n_pos + 1) / 2.0
    return u_statistic / (n_pos * n_neg)


def poisson_log_likelihood(
    observed_counts: Sequence[int],
    forecast_rates: Sequence[float],
    *,
    rate_floor: float = _RATE_FLOOR,
) -> float:
    """Joint Poisson log-likelihood, `sum_i logpmf(n_i; lambda_i)`. This is
    `point_process_log_likelihood` in config/evaluation-protocol.yaml, and
    is reused as the objective inside the L/S/M CSEP consistency tests.
    Rates are floored (not clipped to zero) purely so log(0) never fires;
    a forecast of genuinely zero probability is never actually produced
    by generate_forecast_cells (Poisson approximation keeps it in (0, 1)).
    """
    n = np.asarray(observed_counts, dtype=float)
    lam = np.clip(np.asarray(forecast_rates, dtype=float), rate_floor, None)
    return float(np.sum(n * np.log(lam) - lam - np.array([math.lgamma(k + 1.0) for k in n])))


def poisson_deviance(
    observed_counts: Sequence[int],
    forecast_rates: Sequence[float],
    *,
    rate_floor: float = _RATE_FLOOR,
) -> float:
    """Standard Poisson (saturated-model) deviance, `2 * sum(n*log(n/lambda) - (n - lambda))`,
    with the usual `n=0` convention that the `n*log(n/lambda)` term is 0.
    """
    n = np.asarray(observed_counts, dtype=float)
    lam = np.clip(np.asarray(forecast_rates, dtype=float), rate_floor, None)
    n_safe = np.where(n > 0, n, 1.0)  # avoid log(0); the where() below discards this branch anyway
    term = np.where(n > 0, n * np.log(n_safe / lam), 0.0)
    return float(2.0 * np.sum(term - (n - lam)))


def predictive_coverage(
    observed_counts: Sequence[int], forecast_rates: Sequence[float], *, coverage_level: float = 0.90
) -> float:
    """Fraction of (cell, magnitude-bin) cases whose observed count falls
    within the model's own Poisson predictive interval at `coverage_level`.
    A well-calibrated count forecast should cover close to `coverage_level`
    of cases -- this is a diagnostic, not a hypothesis test with a
    pass/fail verdict. Equal-tailed intervals over a discrete distribution
    cannot hit an exact tail probability (the CDF is a step function), so
    true coverage is systematically >= `coverage_level`, most visibly at
    small rates -- conservative, not miscalibrated.
    """
    n = np.asarray(observed_counts, dtype=float)
    lam = np.clip(np.asarray(forecast_rates, dtype=float), _RATE_FLOOR, None)
    alpha = 1.0 - coverage_level
    lower = stats.poisson.ppf(alpha / 2.0, lam)
    upper = stats.poisson.ppf(1.0 - alpha / 2.0, lam)
    covered = (n >= lower) & (n <= upper)
    return float(np.mean(covered))


def information_gain_per_event(
    observed_counts: Sequence[int], model_rates: Sequence[float], reference_rates: Sequence[float]
) -> float | None:
    """`(LL_model - LL_reference) / N_obs`, in nats per observed event
    (Rhoades et al. 2011; Zechar et al. 2010's IGPE). Positive means the
    model forecast explains the observed catalog better than the supplied
    reference forecast. `None` when zero events were observed (division
    undefined, not zero).
    """
    n_obs = float(np.sum(observed_counts))
    if n_obs == 0:
        return None
    ll_model = poisson_log_likelihood(observed_counts, model_rates)
    ll_reference = poisson_log_likelihood(observed_counts, reference_rates)
    return (ll_model - ll_reference) / n_obs
