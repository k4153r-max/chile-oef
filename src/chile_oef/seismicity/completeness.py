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
