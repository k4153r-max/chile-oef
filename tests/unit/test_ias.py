import math

import numpy as np
import pytest

from chile_oef.seismicity.etas import EtasParameters
from chile_oef.seismicity.ias import IasPolicy, estimate_ias


def _params() -> EtasParameters:
    return EtasParameters(mu_per_day=1.0, k0=0.043, alpha=1.0, c_days=0.1, p_exponent=1.2)


def test_below_minimum_historical_windows_is_not_estimable() -> None:
    result = estimate_ias(
        [1.0, 2.0, 3.0],
        [3.5, 3.6, 3.7],
        reference_magnitude=3.0,
        etas_parameters=_params(),
        evaluation_end_days=10.0,
        policy=IasPolicy(evaluation_window_days=7.0, minimum_historical_windows=30),
    )
    assert result.support_state == "not_estimable"
    assert result.ias_score is None


def test_deficit_is_not_anomalous() -> None:
    """A quiet window (fewer events than expected) must score deviance 0,
    not some symmetric negative anomaly -- docs/ias.md's "one-sided" design.
    """
    rng = np.random.default_rng(3)
    # Steady background-only history (no clustering signal) so expected
    # counts per week track the background rate closely.
    times = sorted(rng.uniform(0.0, 300.0, size=300).tolist())
    magnitudes = [3.5] * len(times)
    result = estimate_ias(
        times,
        magnitudes,
        reference_magnitude=3.0,
        etas_parameters=_params(),
        evaluation_end_days=290.0,
        policy=IasPolicy(evaluation_window_days=7.0, minimum_historical_windows=20),
    )
    assert result.support_state == "estimable"
    component = result.components[0]
    if component.observed_count <= component.expected_count:
        assert component.deviance == 0.0


def _integral_rate(c: float, p: float, d: float) -> float:
    if d <= 0:
        return 0.0
    if abs(p - 1.0) < 1e-8:
        return math.log(d + c) - math.log(c)
    return ((d + c) ** (1.0 - p) - c ** (1.0 - p)) / (1.0 - p)


def _sample_gr_magnitude(rng: np.random.Generator, b: float, mc: float, mmax: float = 8.0) -> float:
    beta = b * math.log(10.0)
    u = rng.uniform(0.0, 1.0)
    return mc - math.log(1.0 - u * (1.0 - math.exp(-beta * (mmax - mc)))) / beta


def _simulate_temporal_etas(
    *,
    mu: float,
    k0: float,
    alpha: float,
    c: float,
    p: float,
    mc: float,
    b: float,
    duration_days: float,
    seed: int,
) -> list[tuple[float, float]]:
    """Same branching-process simulation as tests/unit/test_etas.py,
    independently re-derived here rather than imported, so a shared bug in
    both wouldn't cancel out."""
    rng = np.random.default_rng(seed)
    background_count = rng.poisson(mu * duration_days)
    events: list[tuple[float, float]] = []
    queue: list[tuple[float, float]] = []
    for _ in range(background_count):
        t0 = float(rng.uniform(0.0, duration_days))
        m0 = _sample_gr_magnitude(rng, b, mc)
        events.append((t0, m0))
        queue.append((t0, m0))
    while queue:
        if len(events) > 20_000:
            raise RuntimeError("synthetic catalog exploded")
        parent_time, parent_magnitude = queue.pop()
        remaining = duration_days - parent_time
        if remaining <= 0:
            continue
        productivity = k0 * math.exp(alpha * (parent_magnitude - mc))
        total_expected = productivity * _integral_rate(c, p, remaining)
        n = min(rng.poisson(total_expected), 2000)
        if n == 0:
            continue
        u = rng.uniform(0.0, total_expected, size=n)
        base = c ** (1.0 - p) + u * (1.0 - p) / productivity
        offsets = base ** (1.0 / (1.0 - p)) - c
        for offset in offsets:
            child_time = parent_time + float(offset)
            if child_time > duration_days:
                continue
            child_magnitude = _sample_gr_magnitude(rng, b, mc)
            events.append((child_time, child_magnitude))
            queue.append((child_time, child_magnitude))
    events.sort()
    return events


def test_injected_burst_scores_near_maximum_ias() -> None:
    """The core claim: a burst of events far exceeding what the fitted
    ETAS model expects, right at the evaluation window, must score close
    to IAS=100 -- ranked more anomalous than nearly all historical windows
    of the same catalog. A quiet, typical window (evaluated earlier in the
    same catalog, no injected burst) must score noticeably lower. Both
    checks use the *same* historical reference distribution logic, so this
    isolates the burst's effect rather than some difference in setup.
    """
    mu_true, k0_true, alpha_true, c_true, p_true = 1.0, 0.043, 1.0, 0.1, 1.2
    mc, b = 3.0, 1.0
    duration_days = 400.0
    events = _simulate_temporal_etas(
        mu=mu_true,
        k0=k0_true,
        alpha=alpha_true,
        c=c_true,
        p=p_true,
        mc=mc,
        b=b,
        duration_days=duration_days,
        seed=42,
    )
    assert len(events) >= 300, "synthetic catalog too small for this seed"

    t = [event[0] for event in events]
    m = [event[1] for event in events]
    params = EtasParameters(
        mu_per_day=mu_true, k0=k0_true, alpha=alpha_true, c_days=c_true, p_exponent=p_true
    )
    policy = IasPolicy(evaluation_window_days=7.0, minimum_historical_windows=20)

    normal_result = estimate_ias(
        t,
        m,
        reference_magnitude=mc,
        etas_parameters=params,
        evaluation_end_days=350.0,
        policy=policy,
    )
    assert normal_result.support_state == "estimable"

    rng = np.random.default_rng(99)
    burst_count = 30
    burst_times = rng.uniform(350.0 - 7.0, 350.0, size=burst_count).tolist()
    burst_magnitudes = [_sample_gr_magnitude(rng, b, mc) for _ in range(burst_count)]

    anomalous_result = estimate_ias(
        t + burst_times,
        m + burst_magnitudes,
        reference_magnitude=mc,
        etas_parameters=params,
        evaluation_end_days=350.0,
        policy=policy,
    )
    assert anomalous_result.support_state == "estimable"
    assert anomalous_result.ias_score is not None
    assert anomalous_result.ias_score >= 95.0
    assert (
        anomalous_result.components[0].observed_count
        > anomalous_result.components[0].expected_count
    )
    assert anomalous_result.components[0].deviance > normal_result.components[0].deviance
    # The injected burst must not have been "explained away" by the model:
    # its expected count should be essentially the same as the normal
    # window's (same history up to the window start in both cases).
    assert anomalous_result.components[0].expected_count == pytest.approx(
        normal_result.components[0].expected_count, rel=0.05
    )


def test_method_and_calibration_metadata() -> None:
    rng = np.random.default_rng(1)
    times = sorted(rng.uniform(0.0, 300.0, size=300).tolist())
    magnitudes = [3.5] * len(times)
    result = estimate_ias(
        times,
        magnitudes,
        reference_magnitude=3.0,
        etas_parameters=_params(),
        evaluation_end_days=290.0,
        policy=IasPolicy(minimum_historical_windows=20),
    )
    assert result.method_version == "ias_etas_count_deviance_v1"
    assert result.calibration_status == "uncalibrated_anomaly_index"
    assert result.diagnostics["network_epoch_aware"] is False
    assert result.components[0].name == "etas_count_deviance"
