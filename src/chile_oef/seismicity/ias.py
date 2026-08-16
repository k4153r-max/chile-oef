import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from chile_oef.seismicity.etas import EtasParameters
from chile_oef.seismicity.modified_omori import _integral_rate


@dataclass(frozen=True)
class IasPolicy:
    version: int = 1
    status: str = "experimental"
    method_version: str = "ias_etas_count_deviance_v1"
    # Explicitly not "calibrated forecast probability": IAS is a historical
    # percentile of an anomaly statistic, per docs/ias.md, and must never be
    # relabeled as one.
    calibration_status: str = "uncalibrated_anomaly_index"
    evaluation_window_days: float = 7.0
    minimum_historical_windows: int = 30


@dataclass(frozen=True)
class IasComponent:
    name: str
    observed_count: int
    expected_count: float
    deviance: float


@dataclass(frozen=True)
class IasResult:
    evaluation_start_days: float
    evaluation_end_days: float
    support_state: str
    ias_score: float | None
    historical_window_count: int
    components: tuple[IasComponent, ...]
    method_version: str
    calibration_status: str
    diagnostics: dict[str, Any]


def _poisson_deviance_one_sided(observed: int, expected: float) -> float:
    """One-sided anomaly deviance (docs/ias.md): only *excess* activity is
    anomalous. A deficit (observed <= expected) is not treated as anomalous
    and scores 0, matching IAS's stated purpose (activity anomaly, not a
    two-sided goodness-of-fit statistic).
    """
    if expected <= 0:
        return 0.0 if observed == 0 else math.inf
    if observed <= expected:
        return 0.0
    return 2.0 * (observed * math.log(observed / expected) - (observed - expected))


def _etas_expected_count(
    window_start_days: float,
    window_end_days: float,
    *,
    parameters: EtasParameters,
    reference_magnitude: float,
    prior_event_times_days: Sequence[float],
    prior_event_magnitudes: Sequence[float],
) -> float:
    """Expected event count in [window_start, window_end) under the
    already-fit temporal ETAS conditional intensity, using only events
    strictly before window_start -- the same availability invariant as
    everywhere else in this project (forecast_time < event_time): events
    that would occur inside the evaluation window itself must not
    contribute to their own window's expectation.
    """
    duration = window_end_days - window_start_days
    total = parameters.mu_per_day * duration
    for event_time, event_magnitude in zip(
        prior_event_times_days, prior_event_magnitudes, strict=True
    ):
        if event_time >= window_start_days:
            continue
        productivity = parameters.k0 * math.exp(
            parameters.alpha * (event_magnitude - reference_magnitude)
        )
        total += productivity * (
            _integral_rate(parameters.c_days, parameters.p_exponent, window_end_days - event_time)
            - _integral_rate(
                parameters.c_days, parameters.p_exponent, window_start_days - event_time
            )
        )
    return total


def estimate_ias(
    event_times_days: Sequence[float],
    event_magnitudes: Sequence[float],
    *,
    reference_magnitude: float,
    etas_parameters: EtasParameters,
    evaluation_end_days: float,
    policy: IasPolicy | None = None,
) -> IasResult:
    """Seismic Anomaly Index (docs/ias.md): IAS = 100 * F(D), where D is a
    one-sided ETAS count-residual deviance for the most recent evaluation
    window and F is D's empirical percentile against a historical reference
    distribution of the same statistic computed over earlier,
    non-overlapping windows of the same length in this same catalog/region.

    This is one component only (ETAS count residual). docs/ias.md lists
    energy-proxy residuals, spatial concentration, persistence, and
    depth-migration as further candidate components for a future slice;
    combining components must not double-count correlated signals, which is
    exactly why they are not attempted here yet.

    Not "network-epoch-aware" yet (docs/ias.md's stated design target): the
    historical reference distribution is drawn from this catalog's own
    history without adjusting for detection-capability changes over network
    epochs. A documented simplification, not a silent one.

    IAS is an anomaly index, not seismic hazard or a forecast probability
    (docs/ias.md, docs/communication-policy.md): it must never be presented
    as "an earthquake is coming" or similar.
    """
    policy = policy or IasPolicy()
    window_days = policy.evaluation_window_days
    evaluation_start_days = evaluation_end_days - window_days
    diagnostics: dict[str, Any] = {
        "estimator": "ias_etas_count_deviance",
        "evaluation_window_days": window_days,
        "components_implemented": ["etas_count_deviance"],
        "components_not_yet_implemented": [
            "energy_proxy_residual",
            "spatial_concentration",
            "persistence",
            "depth_migration",
        ],
        "network_epoch_aware": False,
    }

    ordered_times = sorted(event_times_days)
    ordered_pairs = sorted(zip(event_times_days, event_magnitudes, strict=True))

    def _count_in_window(start: float, end: float) -> int:
        return sum(1 for t in ordered_times if start <= t < end)

    def _prior_events(before: float) -> tuple[list[float], list[float]]:
        prior = [(t, m) for t, m in ordered_pairs if t < before]
        return [t for t, _ in prior], [m for _, m in prior]

    current_observed = _count_in_window(evaluation_start_days, evaluation_end_days)
    prior_times, prior_magnitudes = _prior_events(evaluation_start_days)
    current_expected = _etas_expected_count(
        evaluation_start_days,
        evaluation_end_days,
        parameters=etas_parameters,
        reference_magnitude=reference_magnitude,
        prior_event_times_days=prior_times,
        prior_event_magnitudes=prior_magnitudes,
    )
    current_deviance = _poisson_deviance_one_sided(current_observed, current_expected)

    historical_deviances: list[float] = []
    window_end_cursor = evaluation_start_days
    earliest_time = ordered_times[0] if ordered_times else 0.0
    while window_end_cursor - window_days >= earliest_time:
        window_start = window_end_cursor - window_days
        observed = _count_in_window(window_start, window_end_cursor)
        prior_times_h, prior_magnitudes_h = _prior_events(window_start)
        expected = _etas_expected_count(
            window_start,
            window_end_cursor,
            parameters=etas_parameters,
            reference_magnitude=reference_magnitude,
            prior_event_times_days=prior_times_h,
            prior_event_magnitudes=prior_magnitudes_h,
        )
        historical_deviances.append(_poisson_deviance_one_sided(observed, expected))
        window_end_cursor = window_start

    diagnostics["historical_window_count"] = len(historical_deviances)
    component = IasComponent(
        name="etas_count_deviance",
        observed_count=current_observed,
        expected_count=current_expected,
        deviance=current_deviance,
    )

    if len(historical_deviances) < policy.minimum_historical_windows:
        diagnostics["reason"] = "fewer_than_minimum_historical_windows"
        return IasResult(
            evaluation_start_days=evaluation_start_days,
            evaluation_end_days=evaluation_end_days,
            support_state="not_estimable",
            ias_score=None,
            historical_window_count=len(historical_deviances),
            components=(component,),
            method_version=policy.method_version,
            calibration_status=policy.calibration_status,
            diagnostics=diagnostics,
        )

    at_or_below = sum(1 for d in historical_deviances if d <= current_deviance)
    ias_score = 100.0 * at_or_below / len(historical_deviances)

    return IasResult(
        evaluation_start_days=evaluation_start_days,
        evaluation_end_days=evaluation_end_days,
        support_state="estimable",
        ias_score=ias_score,
        historical_window_count=len(historical_deviances),
        components=(component,),
        method_version=policy.method_version,
        calibration_status=policy.calibration_status,
        diagnostics=diagnostics,
    )
