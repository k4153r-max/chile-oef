import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy import optimize
from scipy.stats import norm


@dataclass(frozen=True)
class CompletenessPolicy:
    version: int = 1
    status: str = "experimental"
    method_version: str = "maximum_curvature_diagnostic_v1"
    calibration_status: str = "uncalibrated_diagnostic_estimator"
    role: str = "diagnostic"
    bin_width_magnitude: float = 0.1
    maximum_curvature_correction_magnitude: float = 0.2
    supported_minimum_events: int = 200
    high_uncertainty_minimum_events: int = 100
    research_only_minimum_events: int = 50
    goodness_of_fit_method_version: str = "goodness_of_fit_diagnostic_v1"
    goodness_of_fit_target_confidence_percent: float = 95.0
    goodness_of_fit_fallback_confidence_percent: float = 90.0
    goodness_of_fit_minimum_events_above_candidate: int = 10
    goodness_of_fit_minimum_bins_above_candidate: int = 10
    emr_method_version: str = "entire_magnitude_range_bootstrap_v1"
    emr_calibration_status: str = "uncalibrated_primary_estimator"
    emr_bootstrap_resamples: int = 200
    emr_bootstrap_seed: int = 20260816
    emr_confidence_level_percent: float = 95.0
    emr_sigma_min_magnitude: float = 0.01
    emr_sigma_max_magnitude: float = 2.0
    emr_beta_min: float = 0.01
    emr_beta_max: float = 10.0


def load_completeness_policy(path: Path) -> CompletenessPolicy:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    keys = CompletenessPolicy.__dataclass_fields__
    values = {key: document[key] for key in keys if key in document}
    return CompletenessPolicy(**values)


def support_state(event_count: int, policy: CompletenessPolicy | None = None) -> str:
    """Classify sample size per the reporting bands in docs/completeness.md.

    These bands are configuration defaults, not a validated precision study;
    they gate whether an Mc value is even computed, not just how it is
    labeled.
    """
    policy = policy or CompletenessPolicy()
    if event_count < 0:
        raise ValueError("event_count must not be negative")
    if event_count >= policy.supported_minimum_events:
        return "supported"
    if event_count >= policy.high_uncertainty_minimum_events:
        return "high_uncertainty"
    if event_count >= policy.research_only_minimum_events:
        return "research_only"
    return "not_estimable"


@dataclass(frozen=True)
class MagnitudeCompletenessEstimate:
    event_count: int
    support_state: str
    mc_value: float | None
    raw_peak_bin_magnitude: float | None
    method_version: str
    role: str
    calibration_status: str
    bin_width_magnitude: float
    diagnostics: dict[str, Any]


def _bin_magnitude(magnitude: float, bin_width: float) -> float:
    # Round on the integer bin index, not the raw magnitude, so values that
    # fall exactly on a bin boundary do not drift into the wrong bin under
    # floating-point error.
    bin_index = round(magnitude / bin_width)
    return round(bin_index * bin_width, 10)


def estimate_mc_maximum_curvature(
    magnitudes: Sequence[float],
    *,
    policy: CompletenessPolicy | None = None,
) -> MagnitudeCompletenessEstimate:
    """Maximum-curvature magnitude of completeness (Wiemer & Wyss, 2000).

    This is the mode of the non-cumulative frequency-magnitude distribution,
    shifted by a fixed correction because the raw mode is a known negative-
    biased estimator of true Mc. Per docs/completeness.md this method is a
    diagnostic cross-check only: the registered primary estimator is Entire
    Magnitude Range with bootstrap uncertainty, not yet implemented.
    """
    policy = policy or CompletenessPolicy()
    event_count = len(magnitudes)
    state = support_state(event_count, policy)
    diagnostics: dict[str, Any] = {
        "estimator": "maximum_curvature",
        "role_reason": (
            "maximum curvature is a diagnostic cross-check only; the registered "
            "primary estimator is entire magnitude range with bootstrap "
            "uncertainty per docs/completeness.md, not yet implemented"
        ),
    }
    if state == "not_estimable":
        diagnostics["reason"] = "fewer_than_minimum_events"
        return MagnitudeCompletenessEstimate(
            event_count=event_count,
            support_state=state,
            mc_value=None,
            raw_peak_bin_magnitude=None,
            method_version=policy.method_version,
            role=policy.role,
            calibration_status=policy.calibration_status,
            bin_width_magnitude=policy.bin_width_magnitude,
            diagnostics=diagnostics,
        )

    histogram: Counter[float] = Counter(
        _bin_magnitude(magnitude, policy.bin_width_magnitude) for magnitude in magnitudes
    )
    # sorted() before max() makes ties deterministic: the smallest magnitude
    # bin wins, which is the conservative (lower) completeness choice.
    raw_peak_bin = max(sorted(histogram), key=lambda bin_value: histogram[bin_value])
    mc_value = round(raw_peak_bin + policy.maximum_curvature_correction_magnitude, 10)
    diagnostics["histogram_bin_count"] = len(histogram)
    diagnostics["raw_peak_bin_event_count"] = histogram[raw_peak_bin]
    return MagnitudeCompletenessEstimate(
        event_count=event_count,
        support_state=state,
        mc_value=mc_value,
        raw_peak_bin_magnitude=raw_peak_bin,
        method_version=policy.method_version,
        role=policy.role,
        calibration_status=policy.calibration_status,
        bin_width_magnitude=policy.bin_width_magnitude,
        diagnostics=diagnostics,
    )


@dataclass(frozen=True)
class GoodnessOfFitEstimate:
    event_count: int
    support_state: str
    mc_value: float | None
    achieved_confidence_percent: float | None
    best_fit_quality_percent: float | None
    method_version: str
    role: str
    calibration_status: str
    bin_width_magnitude: float
    diagnostics: dict[str, Any]


def _bin_range(min_bin: float, max_bin: float, bin_width: float) -> list[float]:
    min_index = round(min_bin / bin_width)
    max_index = round(max_bin / bin_width)
    return [round(index * bin_width, 10) for index in range(min_index, max_index + 1)]


def estimate_mc_goodness_of_fit(
    magnitudes: Sequence[float],
    *,
    policy: CompletenessPolicy | None = None,
) -> GoodnessOfFitEstimate:
    """Goodness-of-fit magnitude of completeness (Wiemer & Wyss, 2000).

    For each candidate bin Mi, ascending, fits a Gutenberg-Richter line by
    Aki (1965) maximum likelihood using only events with binned magnitude
    >= Mi, anchored so the modeled cumulative count matches the observed
    cumulative count exactly at Mi. R(Mi) is the percentage of observed
    cumulative counts (from Mi to the largest observed bin, including empty
    bins in between) reproduced by that modeled line. Mc is the smallest Mi
    reaching the target confidence (95%); if none does, the smallest Mi
    reaching the fallback confidence (90%). If neither is reached, this
    refuses to guess: mc_value is None rather than silently returning the
    best available fit, consistent with "refuse under-supported cells rather
    than returning unstable values" (docs/PROJECT_STATE.md). Per
    docs/completeness.md this method is a cross-check only, not the primary
    estimator.
    """
    policy = policy or CompletenessPolicy()
    event_count = len(magnitudes)
    state = support_state(event_count, policy)
    diagnostics: dict[str, Any] = {
        "estimator": "goodness_of_fit",
        "role_reason": (
            "goodness-of-fit is a cross-check per docs/completeness.md; the "
            "registered primary estimator is entire magnitude range with "
            "bootstrap uncertainty, not yet implemented"
        ),
        "target_confidence_percent": policy.goodness_of_fit_target_confidence_percent,
        "fallback_confidence_percent": policy.goodness_of_fit_fallback_confidence_percent,
    }
    if state == "not_estimable":
        diagnostics["reason"] = "fewer_than_minimum_events"
        return GoodnessOfFitEstimate(
            event_count=event_count,
            support_state=state,
            mc_value=None,
            achieved_confidence_percent=None,
            best_fit_quality_percent=None,
            method_version=policy.goodness_of_fit_method_version,
            role=policy.role,
            calibration_status=policy.calibration_status,
            bin_width_magnitude=policy.bin_width_magnitude,
            diagnostics=diagnostics,
        )

    bin_width = policy.bin_width_magnitude
    binned = [_bin_magnitude(magnitude, bin_width) for magnitude in magnitudes]
    histogram: Counter[float] = Counter(binned)
    full_bins = _bin_range(min(histogram), max(histogram), bin_width)

    # Single descending pass: cumulative[b] = observed count with binned
    # magnitude >= b; weighted_cumulative[b] = sum of binned magnitude over
    # that same set, so the MLE mean magnitude above any candidate is a O(1)
    # lookup rather than an O(n) rescan per candidate.
    cumulative: dict[float, int] = {}
    weighted_cumulative: dict[float, float] = {}
    running_count = 0
    running_weight = 0.0
    for bin_value in reversed(full_bins):
        running_count += histogram.get(bin_value, 0)
        running_weight += histogram.get(bin_value, 0) * bin_value
        cumulative[bin_value] = running_count
        weighted_cumulative[bin_value] = running_weight

    fit_quality_by_candidate: dict[float, float] = {}
    for index, candidate in enumerate(full_bins):
        n_above = cumulative[candidate]
        bins_at_or_above = full_bins[index:]
        # Near the sparse tail, very few magnitude increments remain between
        # the candidate and the largest observed bin: a 2-parameter GR line
        # can trivially "fit" that short, thin range even for pure noise.
        # Requiring a minimum span of bins (not just events) rules out that
        # false-positive regime.
        if (
            n_above < policy.goodness_of_fit_minimum_events_above_candidate
            or len(bins_at_or_above) < policy.goodness_of_fit_minimum_bins_above_candidate
        ):
            continue
        mean_magnitude_above = weighted_cumulative[candidate] / n_above
        denominator = mean_magnitude_above - (candidate - bin_width / 2.0)
        if denominator <= 0:
            continue
        b_value = math.log10(math.e) / denominator
        a_value = math.log10(n_above) + b_value * candidate
        observed_sum = 0.0
        absolute_deviation_sum = 0.0
        for bin_value in bins_at_or_above:
            observed = cumulative[bin_value]
            synthetic = 10 ** (a_value - b_value * bin_value)
            observed_sum += observed
            absolute_deviation_sum += abs(observed - synthetic)
        if observed_sum <= 0:
            continue
        fit_quality_by_candidate[candidate] = 100.0 * (1.0 - absolute_deviation_sum / observed_sum)

    diagnostics["candidates_evaluated"] = len(fit_quality_by_candidate)
    if not fit_quality_by_candidate:
        diagnostics["reason"] = "no_candidate_bin_had_sufficient_events_for_b_value_mle"
        return GoodnessOfFitEstimate(
            event_count=event_count,
            support_state=state,
            mc_value=None,
            achieved_confidence_percent=None,
            best_fit_quality_percent=None,
            method_version=policy.goodness_of_fit_method_version,
            role=policy.role,
            calibration_status=policy.calibration_status,
            bin_width_magnitude=bin_width,
            diagnostics=diagnostics,
        )

    best_candidate = max(fit_quality_by_candidate, key=lambda b: fit_quality_by_candidate[b])
    diagnostics["best_fit_candidate_magnitude"] = best_candidate

    confidence_levels = (
        policy.goodness_of_fit_target_confidence_percent,
        policy.goodness_of_fit_fallback_confidence_percent,
    )
    for level in confidence_levels:
        reaching = sorted(b for b, r in fit_quality_by_candidate.items() if r >= level)
        if reaching:
            mc_value = reaching[0]
            return GoodnessOfFitEstimate(
                event_count=event_count,
                support_state=state,
                mc_value=mc_value,
                achieved_confidence_percent=level,
                best_fit_quality_percent=fit_quality_by_candidate[mc_value],
                method_version=policy.goodness_of_fit_method_version,
                role=policy.role,
                calibration_status=policy.calibration_status,
                bin_width_magnitude=bin_width,
                diagnostics=diagnostics,
            )

    diagnostics["reason"] = "fallback_confidence_threshold_not_reached_at_any_candidate"
    diagnostics["best_fit_quality_percent"] = fit_quality_by_candidate[best_candidate]
    return GoodnessOfFitEstimate(
        event_count=event_count,
        support_state=state,
        mc_value=None,
        achieved_confidence_percent=None,
        best_fit_quality_percent=fit_quality_by_candidate[best_candidate],
        method_version=policy.goodness_of_fit_method_version,
        role=policy.role,
        calibration_status=policy.calibration_status,
        bin_width_magnitude=bin_width,
        diagnostics=diagnostics,
    )


@dataclass(frozen=True)
class EntireMagnitudeRangeEstimate:
    event_count: int
    support_state: str
    mc_value: float | None
    mc_confidence_interval: tuple[float, float] | None
    detection_sigma_magnitude: float | None
    b_value: float | None
    converged: bool
    bootstrap_resamples_converged: int
    method_version: str
    role: str
    calibration_status: str
    bin_width_magnitude: float
    diagnostics: dict[str, Any]


def _emr_expected_counts(theta: np.ndarray, bins: np.ndarray, m0: float) -> np.ndarray:
    mu, sigma, beta, log_n0 = theta
    detection_probability = norm.cdf((bins - mu) / sigma)
    return np.exp(log_n0) * np.exp(-beta * (bins - m0)) * detection_probability


def _emr_negative_log_likelihood(
    theta: np.ndarray, bins: np.ndarray, observed_counts: np.ndarray, m0: float
) -> float:
    # Discretized Poisson-process likelihood: expected count per bin from a
    # Gutenberg-Richter rate thinned by a normal-CDF detection function
    # (Ogata & Katsura, 1993), approximating their continuous-magnitude
    # likelihood at this catalog's bin width.
    predicted = np.clip(_emr_expected_counts(theta, bins, m0), 1e-300, None)
    return float(np.sum(predicted - observed_counts * np.log(predicted)))


def _fit_emr(
    magnitudes: Sequence[float],
    bin_width: float,
    policy: CompletenessPolicy,
    *,
    x0: tuple[float, float, float, float] | None = None,
) -> optimize.OptimizeResult:
    binned = [_bin_magnitude(magnitude, bin_width) for magnitude in magnitudes]
    histogram: Counter[float] = Counter(binned)
    full_bins = _bin_range(min(histogram), max(histogram), bin_width)
    bins = np.array(full_bins, dtype=float)
    observed_counts = np.array(
        [histogram.get(bin_value, 0) for bin_value in full_bins], dtype=float
    )
    m0 = float(bins.min())

    if x0 is None:
        maxc = estimate_mc_maximum_curvature(magnitudes, policy=policy)
        mu0 = (
            maxc.raw_peak_bin_magnitude
            if maxc.raw_peak_bin_magnitude is not None
            else float(np.median(magnitudes))
        )
        events_above = [magnitude for magnitude in magnitudes if magnitude >= mu0]
        if len(events_above) >= 2:
            mean_above = sum(events_above) / len(events_above)
            denominator = mean_above - (mu0 - bin_width / 2.0)
            beta0 = 1.0 / denominator if denominator > 0 else 2.3
        else:
            beta0 = 2.3
        beta0 = min(max(beta0, policy.emr_beta_min), policy.emr_beta_max)
        sigma0 = bin_width * 2.0
        log_n0_0 = math.log(max(float(observed_counts.max()), 1.0))
        x0 = (mu0, sigma0, beta0, log_n0_0)

    bounds = [
        (bins.min() - 1.0, bins.max() + 1.0),
        (policy.emr_sigma_min_magnitude, policy.emr_sigma_max_magnitude),
        (policy.emr_beta_min, policy.emr_beta_max),
        (x0[3] - 20.0, x0[3] + 20.0),
    ]
    return optimize.minimize(
        _emr_negative_log_likelihood,
        x0=np.array(x0, dtype=float),
        args=(bins, observed_counts, m0),
        method="L-BFGS-B",
        bounds=bounds,
    )


def estimate_mc_entire_magnitude_range(
    magnitudes: Sequence[float],
    *,
    policy: CompletenessPolicy | None = None,
) -> EntireMagnitudeRangeEstimate:
    """Entire Magnitude Range Mc with bootstrap uncertainty (Ogata & Katsura,
    1993). This is the registered *primary* estimator in docs/completeness.md
    (Maximum Curvature and Goodness-of-Fit are diagnostic cross-checks only).

    Jointly fits, by maximum likelihood over the full observed magnitude
    range (not just events above a candidate threshold): ``mu``, the
    magnitude at which detection probability is 50% -- reported as
    ``mc_value``; ``sigma``, the width of the detection rolloff; and the
    Gutenberg-Richter ``b`` value. Uncertainty on ``mc_value`` comes from
    nonparametric bootstrap resampling of the catalog, refit each time from
    the point estimate.
    """
    policy = policy or CompletenessPolicy()
    event_count = len(magnitudes)
    state = support_state(event_count, policy)
    diagnostics: dict[str, Any] = {
        "estimator": "entire_magnitude_range",
        "role_reason": "registered primary estimator per docs/completeness.md",
        "confidence_level_percent": policy.emr_confidence_level_percent,
        "bootstrap_resamples_requested": policy.emr_bootstrap_resamples,
    }
    if state == "not_estimable":
        diagnostics["reason"] = "fewer_than_minimum_events"
        return EntireMagnitudeRangeEstimate(
            event_count=event_count,
            support_state=state,
            mc_value=None,
            mc_confidence_interval=None,
            detection_sigma_magnitude=None,
            b_value=None,
            converged=False,
            bootstrap_resamples_converged=0,
            method_version=policy.emr_method_version,
            role="primary",
            calibration_status=policy.emr_calibration_status,
            bin_width_magnitude=policy.bin_width_magnitude,
            diagnostics=diagnostics,
        )

    point_fit = _fit_emr(magnitudes, policy.bin_width_magnitude, policy)
    if not point_fit.success:
        diagnostics["reason"] = "point_estimate_did_not_converge"
        diagnostics["optimizer_message"] = str(point_fit.message)
        return EntireMagnitudeRangeEstimate(
            event_count=event_count,
            support_state=state,
            mc_value=None,
            mc_confidence_interval=None,
            detection_sigma_magnitude=None,
            b_value=None,
            converged=False,
            bootstrap_resamples_converged=0,
            method_version=policy.emr_method_version,
            role="primary",
            calibration_status=policy.emr_calibration_status,
            bin_width_magnitude=policy.bin_width_magnitude,
            diagnostics=diagnostics,
        )

    mu, sigma, beta, _log_n0 = point_fit.x
    b_value = beta / math.log(10.0)

    rng = np.random.default_rng(policy.emr_bootstrap_seed)
    magnitudes_array = np.array(magnitudes, dtype=float)
    bootstrap_mu: list[float] = []
    for _ in range(policy.emr_bootstrap_resamples):
        resample = rng.choice(magnitudes_array, size=magnitudes_array.size, replace=True)
        resample_fit = _fit_emr(
            resample.tolist(),
            policy.bin_width_magnitude,
            policy,
            x0=tuple(point_fit.x),
        )
        if resample_fit.success:
            bootstrap_mu.append(float(resample_fit.x[0]))

    diagnostics["bootstrap_resamples_converged"] = len(bootstrap_mu)
    mc_confidence_interval: tuple[float, float] | None = None
    minimum_resamples_for_interval = max(10, policy.emr_bootstrap_resamples // 4)
    if len(bootstrap_mu) >= minimum_resamples_for_interval:
        half_tail_percent = (100.0 - policy.emr_confidence_level_percent) / 2.0
        lower = float(np.percentile(bootstrap_mu, half_tail_percent))
        upper = float(np.percentile(bootstrap_mu, 100.0 - half_tail_percent))
        mc_confidence_interval = (round(lower, 10), round(upper, 10))
    else:
        diagnostics["reason"] = "insufficient_converged_bootstrap_resamples_for_interval"

    return EntireMagnitudeRangeEstimate(
        event_count=event_count,
        support_state=state,
        mc_value=round(float(mu), 10),
        mc_confidence_interval=mc_confidence_interval,
        detection_sigma_magnitude=round(float(sigma), 10),
        b_value=round(float(b_value), 10),
        converged=True,
        bootstrap_resamples_converged=len(bootstrap_mu),
        method_version=policy.emr_method_version,
        role="primary",
        calibration_status=policy.emr_calibration_status,
        bin_width_magnitude=policy.bin_width_magnitude,
        diagnostics=diagnostics,
    )
