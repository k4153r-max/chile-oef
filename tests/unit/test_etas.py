import math

import numpy as np
import pytest

from chile_oef.seismicity.etas import EtasPolicy, estimate_temporal_etas


def test_below_minimum_events_is_not_estimable() -> None:
    result = estimate_temporal_etas(
        [1.0, 2.0, 3.0], [3.5, 3.6, 3.7], reference_magnitude=3.0, observation_duration_days=10.0
    )
    assert result.support_state == "not_estimable"
    assert result.converged is False
    assert result.parameters is None


def test_observation_duration_shorter_than_last_event_is_rejected() -> None:
    policy = EtasPolicy(minimum_events=5)
    result = estimate_temporal_etas(
        [1.0, 2.0, 3.0, 4.0, 20.0],
        [3.5] * 5,
        reference_magnitude=3.0,
        observation_duration_days=10.0,
        policy=policy,
    )
    assert result.support_state == "not_estimable"
    assert result.diagnostics["reason"] == "observation_duration_shorter_than_last_event"


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


def _sample_offspring_offsets(
    rng: np.random.Generator,
    *,
    k0: float,
    alpha: float,
    c: float,
    p: float,
    mc: float,
    parent_magnitude: float,
    remaining_days: float,
    max_children: int = 2000,
) -> list[float]:
    productivity = k0 * math.exp(alpha * (parent_magnitude - mc))
    total_expected = productivity * _integral_rate(c, p, remaining_days)
    n = min(rng.poisson(total_expected), max_children)
    if n == 0:
        return []
    u = rng.uniform(0.0, total_expected, size=n)
    if abs(p - 1.0) < 1e-8:
        offsets = c * np.exp(u / productivity) - c
    else:
        base = c ** (1.0 - p) + u * (1.0 - p) / productivity
        offsets = base ** (1.0 / (1.0 - p)) - c
    return offsets.tolist()


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
    max_events: int = 20_000,
) -> list[tuple[float, float]]:
    """Branching-process (Hawkes) simulation of the exact temporal ETAS
    model the estimator fits, generating offspring only within the finite
    observation window -- this is an independent re-derivation (not a call
    into the module under test) of the same conditional-intensity model,
    the only reliable way to validate an ETAS MLE (standard practice in the
    ETAS literature, e.g. Ogata's own validation approach). Raises if the
    process is supercritical (branching ratio >= 1) rather than silently
    truncating an exploding catalog.
    """
    rng = np.random.default_rng(seed)
    background_count = rng.poisson(mu * duration_days)
    events: list[tuple[float, float]] = []
    queue: list[tuple[float, float]] = []
    for _ in range(background_count):
        event_time = rng.uniform(0.0, duration_days)
        magnitude = _sample_gr_magnitude(rng, b, mc)
        events.append((event_time, magnitude))
        queue.append((event_time, magnitude))
    while queue:
        if len(events) > max_events:
            raise RuntimeError("synthetic ETAS catalog exploded (supercritical parameters)")
        parent_time, parent_magnitude = queue.pop()
        remaining_days = duration_days - parent_time
        if remaining_days <= 0:
            continue
        offsets = _sample_offspring_offsets(
            rng,
            k0=k0,
            alpha=alpha,
            c=c,
            p=p,
            mc=mc,
            parent_magnitude=parent_magnitude,
            remaining_days=remaining_days,
        )
        for offset in offsets:
            child_time = parent_time + offset
            if child_time > duration_days:
                continue
            child_magnitude = _sample_gr_magnitude(rng, b, mc)
            events.append((child_time, child_magnitude))
            queue.append((child_time, child_magnitude))
    events.sort()
    return events


def test_recovers_known_etas_parameters_on_a_synthetic_catalog() -> None:
    """A 5-parameter joint MLE with an O(n^2) likelihood is materially
    harder to identify precisely than Modified Omori's 2-parameter
    per-family fit, especially k0/alpha/c, which trade off against each
    other when triggered events are a minority of the catalog (a
    well-documented ETAS estimation characteristic in the literature, not a
    weakness specific to this implementation). Tolerances reflect that:
    mu and p (the best-identified parameters here) get tighter bounds than
    k0/alpha/c. This is a fixed-seed, fully deterministic scenario (no
    scipy/numpy randomness varies between runs), chosen specifically because
    it does NOT land on a parameter-bound boundary -- smaller/noisier
    synthetic catalogs were tried during development and some genuinely do
    hit boundaries (alpha=0, p=3), which is expected behavior for weak
    triggering signal, not something to paper over with a larger tolerance
    here.
    """
    mu_true, k0_true, alpha_true, c_true, p_true = 1.0, 0.043, 1.0, 0.1, 1.2
    mc, b = 3.0, 1.0
    duration_days = 300.0

    events = _simulate_temporal_etas(
        mu=mu_true,
        k0=k0_true,
        alpha=alpha_true,
        c=c_true,
        p=p_true,
        mc=mc,
        b=b,
        duration_days=duration_days,
        seed=7,
    )
    assert len(events) >= 150, "synthetic catalog too small for this seed"

    t = [event[0] for event in events]
    m = [event[1] for event in events]
    policy = EtasPolicy(restarts=2, minimum_events=100)
    result = estimate_temporal_etas(
        t, m, reference_magnitude=mc, observation_duration_days=duration_days, policy=policy
    )

    assert result.converged is True
    assert result.support_state == "estimable"
    assert result.restarts_converged >= 1
    params = result.parameters
    assert params is not None
    assert params.mu_per_day == pytest.approx(mu_true, rel=0.3)
    assert params.p_exponent == pytest.approx(p_true, abs=0.2)
    assert params.alpha == pytest.approx(alpha_true, abs=0.3)
    # k0 and c trade off against each other through the likelihood integral
    # and are the least precisely identified parameters here: order of
    # magnitude and sign, not close numeric agreement, is the claim.
    assert 0.3 * k0_true < params.k0 < 3.0 * k0_true
    assert 0.3 * c_true < params.c_days < 3.0 * c_true


def test_method_and_calibration_metadata() -> None:
    rng = np.random.default_rng(1)
    t = sorted(rng.uniform(0.0, 10.0, size=150).tolist())
    m = [3.5] * 150
    result = estimate_temporal_etas(
        t,
        m,
        reference_magnitude=3.0,
        observation_duration_days=10.0,
        policy=EtasPolicy(minimum_events=100, restarts=1),
    )
    assert result.method_version == "temporal_etas_mle_v1"
    assert result.calibration_status == "uncalibrated_mle_estimator"
