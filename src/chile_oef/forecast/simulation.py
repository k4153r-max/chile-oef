import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from chile_oef.forecast.specification import MagnitudeBin
from chile_oef.seismicity.modified_omori import _integral_rate
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasParameters


@dataclass(frozen=True)
class CatalogSimulationPolicy:
    simulations: int = 500
    seed: int = 20_260_822
    maximum_events_per_catalog: int = 50_000
    maximum_magnitude: float = 9.5
    method_version: str = "etas_branching_catalog_counts_v1"


@dataclass(frozen=True)
class PredictiveCountSummary:
    support_state: str
    mean: float | None
    median: float | None
    p025: float | None
    p05: float | None
    p95: float | None
    p975: float | None
    probability_at_least_one: float | None


@dataclass(frozen=True)
class CatalogSimulationResult:
    simulation_count: int
    total_count: PredictiveCountSummary
    magnitude_bins: tuple[dict[str, Any], ...]
    method_version: str
    diagnostics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sample_gr_magnitudes(
    rng: np.random.Generator,
    count: int,
    *,
    b_value: float,
    reference_magnitude: float,
    maximum_magnitude: float,
) -> np.ndarray:
    if count <= 0:
        return np.empty(0, dtype=float)
    truncated_mass = 1.0 - 10.0 ** (-b_value * (maximum_magnitude - reference_magnitude))
    u = rng.random(count)
    return reference_magnitude - np.log10(1.0 - u * truncated_mass) / b_value


def _sample_omori_offsets(
    rng: np.random.Generator,
    count: int,
    *,
    c_days: float,
    p_exponent: float,
    lower_days: float,
    upper_days: float,
) -> np.ndarray:
    if count <= 0 or upper_days <= lower_days:
        return np.empty(0, dtype=float)
    u = rng.random(count)
    if abs(p_exponent - 1.0) < 1e-8:
        log_lower = math.log(lower_days + c_days)
        log_upper = math.log(upper_days + c_days)
        return np.exp(log_lower + u * (log_upper - log_lower)) - c_days
    exponent = 1.0 - p_exponent
    lower_power = (lower_days + c_days) ** exponent
    upper_power = (upper_days + c_days) ** exponent
    return (lower_power + u * (upper_power - lower_power)) ** (1.0 / exponent) - c_days


def _summary(counts: np.ndarray, *, estimable: bool = True) -> PredictiveCountSummary:
    if not estimable:
        return PredictiveCountSummary(
            support_state="not_estimable",
            mean=None,
            median=None,
            p025=None,
            p05=None,
            p95=None,
            p975=None,
            probability_at_least_one=None,
        )
    return PredictiveCountSummary(
        support_state="estimable",
        mean=float(np.mean(counts)),
        median=float(np.median(counts)),
        p025=float(np.percentile(counts, 2.5)),
        p05=float(np.percentile(counts, 5.0)),
        p95=float(np.percentile(counts, 95.0)),
        p975=float(np.percentile(counts, 97.5)),
        probability_at_least_one=float(np.mean(counts >= 1)),
    )


def simulate_predictive_catalog_counts(
    *,
    prior_event_times_days: Sequence[float],
    prior_event_magnitudes: Sequence[float],
    etas_parameters: SpatiotemporalEtasParameters,
    b_value: float,
    reference_magnitude: float,
    validity_start_days: float,
    validity_end_days: float,
    magnitude_bins: Sequence[MagnitudeBin],
    policy: CatalogSimulationPolicy | None = None,
) -> CatalogSimulationResult:
    """Simulate full future ETAS branching in time/magnitude at fixed parameters.

    These are whole-plane integrated count catalogs. They retain secondary
    triggering and the resulting overdispersion, but intentionally do not claim
    spatial or parameter uncertainty.
    """
    policy = policy or CatalogSimulationPolicy()
    if policy.simulations <= 0:
        raise ValueError("simulations must be positive")
    if validity_end_days <= validity_start_days:
        raise ValueError("validity_end_days must be after validity_start_days")
    if len(prior_event_times_days) != len(prior_event_magnitudes):
        raise ValueError("prior event time and magnitude arrays must have equal length")
    if b_value <= 0:
        raise ValueError("b_value must be positive")
    if policy.maximum_magnitude <= reference_magnitude:
        raise ValueError("maximum_magnitude must exceed reference_magnitude")

    seed = np.random.SeedSequence([policy.seed, int(round(validity_start_days * 86400.0))])
    rng = np.random.default_rng(seed)
    total_counts = np.zeros(policy.simulations, dtype=int)
    bin_counts = np.zeros((policy.simulations, len(magnitude_bins)), dtype=int)
    prior = list(zip(prior_event_times_days, prior_event_magnitudes, strict=True))
    duration_days = validity_end_days - validity_start_days

    for simulation_index in range(policy.simulations):
        future: list[tuple[float, float]] = []
        background_count = int(rng.poisson(etas_parameters.mu_per_day * duration_days))
        if background_count:
            background_times = rng.uniform(validity_start_days, validity_end_days, background_count)
            background_magnitudes = _sample_gr_magnitudes(
                rng,
                background_count,
                b_value=b_value,
                reference_magnitude=reference_magnitude,
                maximum_magnitude=policy.maximum_magnitude,
            )
            future.extend(
                zip(background_times.tolist(), background_magnitudes.tolist(), strict=True)
            )

        parent_index = 0
        parents = [*prior, *future]
        while parent_index < len(parents):
            if len(future) > policy.maximum_events_per_catalog:
                raise RuntimeError(
                    "predictive ETAS catalog exceeded maximum_events_per_catalog; "
                    "refusing a truncated distribution"
                )
            parent_time, parent_magnitude = parents[parent_index]
            parent_index += 1
            lower = max(0.0, validity_start_days - parent_time)
            upper = validity_end_days - parent_time
            if upper <= lower:
                continue
            productivity = etas_parameters.k0 * math.exp(
                etas_parameters.alpha * (parent_magnitude - reference_magnitude)
            )
            expected_children = productivity * (
                _integral_rate(etas_parameters.c_days, etas_parameters.p_exponent, upper)
                - _integral_rate(etas_parameters.c_days, etas_parameters.p_exponent, lower)
            )
            child_count = int(rng.poisson(expected_children))
            if child_count == 0:
                continue
            offsets = _sample_omori_offsets(
                rng,
                child_count,
                c_days=etas_parameters.c_days,
                p_exponent=etas_parameters.p_exponent,
                lower_days=lower,
                upper_days=upper,
            )
            child_times = parent_time + offsets
            child_magnitudes = _sample_gr_magnitudes(
                rng,
                child_count,
                b_value=b_value,
                reference_magnitude=reference_magnitude,
                maximum_magnitude=policy.maximum_magnitude,
            )
            children = list(zip(child_times.tolist(), child_magnitudes.tolist(), strict=True))
            future.extend(children)
            parents.extend(children)

        magnitudes = np.asarray([magnitude for _time, magnitude in future], dtype=float)
        total_counts[simulation_index] = len(magnitudes)
        for bin_index, magnitude_bin in enumerate(magnitude_bins):
            if magnitude_bin.lower < reference_magnitude:
                continue
            selected = magnitudes >= magnitude_bin.lower
            if magnitude_bin.upper is not None:
                selected &= magnitudes < magnitude_bin.upper
            bin_counts[simulation_index, bin_index] = int(np.sum(selected))

    magnitude_summaries = tuple(
        {
            "lower": magnitude_bin.lower,
            "upper": magnitude_bin.upper,
            **asdict(
                _summary(
                    bin_counts[:, index],
                    estimable=magnitude_bin.lower >= reference_magnitude,
                )
            ),
        }
        for index, magnitude_bin in enumerate(magnitude_bins)
    )
    return CatalogSimulationResult(
        simulation_count=policy.simulations,
        total_count=_summary(total_counts),
        magnitude_bins=magnitude_summaries,
        method_version=policy.method_version,
        diagnostics={
            "aleatory_branching_uncertainty": True,
            "parameter_uncertainty": False,
            "spatial_distribution": False,
            "spatial_scope": "whole_plane_integrated_counts",
            "maximum_magnitude": policy.maximum_magnitude,
            "seed": policy.seed,
        },
    )
