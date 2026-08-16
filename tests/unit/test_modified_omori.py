import numpy as np
import pytest

from chile_oef.seismicity.modified_omori import ModifiedOmoriPolicy, estimate_modified_omori


def test_below_minimum_sample_is_not_estimable() -> None:
    result = estimate_modified_omori([0.1, 0.5, 1.0], observation_duration_days=10.0)
    assert result.support_state == "not_estimable"
    assert result.converged is False
    assert result.k_productivity is None
    assert result.c_days is None
    assert result.p_exponent is None


def test_observation_duration_shorter_than_last_event_is_rejected() -> None:
    """Using max(event_times) as the observation window (rather than the
    true end of the analysis window) would truncation-bias the fit; this
    guards against passing a duration that couldn't possibly be the real
    window because an event falls after it.
    """
    result = estimate_modified_omori([1.0, 2.0, 15.0] + [3.0] * 20, observation_duration_days=10.0)
    assert result.support_state == "not_estimable"
    assert result.diagnostics["reason"] == "observation_duration_shorter_than_last_event"


def _cumulative_count(t: float, k: float, c: float, p: float) -> float:
    if abs(p - 1.0) < 1e-8:
        return k * (np.log(t + c) - np.log(c))
    return k * ((t + c) ** (1.0 - p) - c ** (1.0 - p)) / (1.0 - p)


def _sample_modified_omori_sequence(
    *, k: float, c: float, p: float, duration_days: float, seed: int
) -> list[float]:
    """Inverse-CDF sample from a non-homogeneous Poisson process with rate
    K/(t+c)^p over [0, duration_days] -- an independent re-derivation of the
    Modified Omori cumulative count, not a call into the module under test,
    so a shared bug in both wouldn't cancel out.
    """
    rng = np.random.default_rng(seed)
    total_expected = _cumulative_count(duration_days, k, c, p)
    n = rng.poisson(total_expected)
    u = rng.uniform(0.0, total_expected, size=n)
    if abs(p - 1.0) < 1e-8:
        t = c * np.exp(u / k) - c
    else:
        base = c ** (1.0 - p) + u * (1.0 - p) / k
        t = base ** (1.0 / (1.0 - p)) - c
    return sorted(float(value) for value in t)


def test_recovers_known_omori_parameters_on_a_synthetic_sequence() -> None:
    k_true, c_true, p_true, duration = 50.0, 0.05, 1.1, 30.0
    event_times = _sample_modified_omori_sequence(
        k=k_true, c=c_true, p=p_true, duration_days=duration, seed=11
    )
    result = estimate_modified_omori(event_times, observation_duration_days=duration)

    assert result.converged is True
    assert result.support_state == "estimable"
    assert result.p_exponent == pytest.approx(p_true, abs=0.15)
    assert result.c_days == pytest.approx(c_true, abs=0.03)
    # K is the most sample-variance-sensitive parameter (it compounds errors
    # in c and p through the profile-likelihood integral): a looser relative
    # bound reflects that, not a weaker claim about the estimator itself.
    assert result.k_productivity == pytest.approx(k_true, rel=0.35)


def test_faster_decaying_sequence_recovers_a_larger_p() -> None:
    duration = 20.0
    slow_decay = _sample_modified_omori_sequence(
        k=40.0, c=0.1, p=0.8, duration_days=duration, seed=21
    )
    fast_decay = _sample_modified_omori_sequence(
        k=40.0, c=0.1, p=1.6, duration_days=duration, seed=22
    )
    slow_result = estimate_modified_omori(slow_decay, observation_duration_days=duration)
    fast_result = estimate_modified_omori(fast_decay, observation_duration_days=duration)

    assert slow_result.converged and fast_result.converged
    assert slow_result.p_exponent < fast_result.p_exponent


def test_method_and_calibration_metadata() -> None:
    event_times = _sample_modified_omori_sequence(k=30.0, c=0.1, p=1.0, duration_days=15.0, seed=3)
    policy = ModifiedOmoriPolicy()
    result = estimate_modified_omori(event_times, observation_duration_days=15.0, policy=policy)
    assert result.method_version == "modified_omori_mle_v1"
    assert result.calibration_status == "uncalibrated_mle_estimator"
