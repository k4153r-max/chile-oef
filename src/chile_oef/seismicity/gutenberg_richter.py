import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from chile_oef.seismicity.completeness import CompletenessPolicy, _bin_magnitude, support_state


@dataclass(frozen=True)
class GutenbergRichterEstimate:
    event_count: int
    events_at_or_above_mc: int
    support_state: str
    mc_used: float
    b_value: float | None
    b_value_standard_error: float | None
    a_value: float | None
    method_version: str
    calibration_status: str
    diagnostics: dict[str, Any]


def estimate_b_value(
    magnitudes: Sequence[float],
    *,
    mc: float,
    policy: CompletenessPolicy | None = None,
) -> GutenbergRichterEstimate:
    """Gutenberg-Richter b-value by Aki (1965) maximum likelihood.

    Uses only events at or above a *declared* Mc -- this function does not
    derive Mc itself. Per docs/scientific-methodology.md ("Mc is spatially,
    temporally, and source dependent") and docs/completeness.md ("Every
    downstream statistic stores the Mc result it used"), callers must obtain
    Mc from a registered completeness estimator first
    (`chile_oef.seismicity.completeness`) and pass it in explicitly; the
    persistence layer (`GutenbergRichterEstimate` in
    `db/models/seismicity.py`) records which specific completeness estimate
    row was used, not just a bare float.

    Deliberately does not reuse the `b_value` that Entire Magnitude Range
    fits internally: EMR's b is a byproduct of a joint MLE over the full
    magnitude range (including the sub-threshold detection rolloff), fit for
    a different purpose (finding Mc itself). This is the classical,
    independently-verifiable Aki estimator restricted to events at or above
    the already-declared Mc, which is what docs/scientific-methodology.md
    lists as its own distinct step in the scientific progression.

    Uncertainty uses the Shi & Bolt (1982) standard error, which uses the
    observed sample variance of magnitudes rather than assuming a perfect
    exponential -- Aki's original ``b / sqrt(N)`` systematically
    understates uncertainty when the catalog departs from a pure
    Gutenberg-Richter distribution, which real catalogs always do to some
    degree.
    """
    policy = policy or CompletenessPolicy()
    bin_width = policy.bin_width_magnitude
    mc_binned = _bin_magnitude(mc, bin_width)
    events_at_or_above = [
        binned
        for binned in (_bin_magnitude(magnitude, bin_width) for magnitude in magnitudes)
        if binned >= mc_binned - 1e-9
    ]
    n = len(events_at_or_above)
    state = support_state(n, policy)
    diagnostics: dict[str, Any] = {
        "estimator": "gutenberg_richter_aki_mle",
        "mc_binned": mc_binned,
        "total_catalog_event_count": len(magnitudes),
        "uncertainty_method": "shi_and_bolt_1982",
    }
    if state == "not_estimable":
        diagnostics["reason"] = "fewer_than_minimum_events_at_or_above_mc"
        return GutenbergRichterEstimate(
            event_count=len(magnitudes),
            events_at_or_above_mc=n,
            support_state=state,
            mc_used=mc,
            b_value=None,
            b_value_standard_error=None,
            a_value=None,
            method_version=policy.gutenberg_richter_method_version,
            calibration_status=policy.gutenberg_richter_calibration_status,
            diagnostics=diagnostics,
        )

    mean_magnitude = sum(events_at_or_above) / n
    denominator = mean_magnitude - (mc_binned - bin_width / 2.0)
    if denominator <= 0:
        diagnostics["reason"] = "non_positive_mle_denominator"
        return GutenbergRichterEstimate(
            event_count=len(magnitudes),
            events_at_or_above_mc=n,
            support_state=state,
            mc_used=mc,
            b_value=None,
            b_value_standard_error=None,
            a_value=None,
            method_version=policy.gutenberg_richter_method_version,
            calibration_status=policy.gutenberg_richter_calibration_status,
            diagnostics=diagnostics,
        )

    b_value = math.log10(math.e) / denominator
    variance_term = sum((m - mean_magnitude) ** 2 for m in events_at_or_above) / (n * (n - 1))
    standard_error = 2.30 * (b_value**2) * math.sqrt(variance_term)
    a_value = math.log10(n) + b_value * mc_binned
    diagnostics["mean_magnitude_at_or_above_mc"] = mean_magnitude

    return GutenbergRichterEstimate(
        event_count=len(magnitudes),
        events_at_or_above_mc=n,
        support_state=state,
        mc_used=mc,
        b_value=round(b_value, 10),
        b_value_standard_error=round(standard_error, 10),
        a_value=round(a_value, 10),
        method_version=policy.gutenberg_richter_method_version,
        calibration_status=policy.gutenberg_richter_calibration_status,
        diagnostics=diagnostics,
    )
