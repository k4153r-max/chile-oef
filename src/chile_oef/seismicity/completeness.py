import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


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
