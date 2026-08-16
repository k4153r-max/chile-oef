"""Walk-forward CSEP-style evaluation (docs/backtesting.md, Phase 6 of
docs/scientific-methodology.md, config/evaluation-protocol.yaml). Repeats
`ForecastService.issue_forecast` across a historical window, one real,
persisted `ForecastRun` per issue time, then scores each against what was
actually observed once the catalog has had time to mature
(`adjudication_delay`, per docs/backtesting.md's "adjudicated evaluation
occurs after the registered catalog-maturation delay").

Two reference points anchor this on honesty rather than a fabricated
verdict:

- the information-gain-per-event score compares the model forecast to a
  homogeneous-Poisson baseline (background rate only, k0 forced to 0) --
  this is exactly stage 1 of docs/scientific-methodology.md's scientific
  progression ("Empirical base-rate and homogeneous Poisson"), which had
  never been built as its own artifact until this comparison needed one;
- every score this module computes is only as trustworthy as the input
  catalog it was run against. See docs/PROJECT_STATE.md for the current,
  explicitly limited state of real historical ingestion -- this harness is
  validated here against synthetic/fixture catalogs, the same way every
  other estimator in this project was, and has not yet been run against a
  genuine multi-decade Chilean seismicity history (in particular, no 27F
  Maule evaluation per docs/backtesting.md has been performed).
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from numpy.random import Generator
from sqlalchemy import select
from sqlalchemy.orm import Session

from chile_oef.db.models import (
    EvaluationFoldScore,
    EvaluationRun,
    ForecastCellMagnitudeBin,
    SpatialGrid,
)
from chile_oef.evaluation import csep_tests, scoring
from chile_oef.forecast.generation import ForecastGenerationPolicy, generate_forecast_cells
from chile_oef.forecast.service import ForecastService
from chile_oef.forecast.specification import ForecastSpecification, MagnitudeBin
from chile_oef.seismicity.catalog_selection import fetch_declustering_catalog

_RATE_FLOOR = 1e-12


@dataclass(frozen=True)
class WalkForwardPolicy:
    version: int = 1
    status: str = "experimental"
    method_version: str = "walk_forward_csep_evaluation_v1"
    n_simulations: int = 1000
    csep_alpha: float = 0.05
    reliability_bin_count: int = 10
    predictive_coverage_level: float = 0.90
    # No registered default decision threshold exists (see
    # scoring.threshold_scores); an empty tuple means precision/recall/f1/
    # false_alarm_rate are simply not computed rather than guessed.
    decision_thresholds: tuple[float, ...] = ()
    bootstrap_resamples: int = 2000
    bootstrap_confidence_level: float = 0.90


def _cell_id_for_point(grid: SpatialGrid, latitude: float, longitude: float) -> str | None:
    """Analytic point -> cell assignment, matching
    `chile_oef.tectonics.grid.iter_cells`'s id scheme exactly
    (`f"{grid_id}:r{row:04d}:c{col:04d}"`) so this never needs a spatial
    query. A small epsilon guards a point that floating-point arithmetic
    lands microscopically below an exact cell boundary computed from
    `Decimal` at grid-build time.
    """
    row_count = int(grid.metadata_json["row_count"])
    column_count = int(grid.metadata_json["column_count"])
    resolution = grid.resolution_degrees
    row = math.floor((latitude - grid.min_latitude) / resolution + 1e-9)
    column = math.floor((longitude - grid.min_longitude) / resolution + 1e-9)
    if row < 0 or row >= row_count or column < 0 or column >= column_count:
        return None
    return f"{grid.id}:r{row:04d}:c{column:04d}"


def _magnitude_bin_index(magnitude: float, bins: Sequence[MagnitudeBin]) -> int | None:
    for index, bin_spec in enumerate(bins):
        if magnitude < bin_spec.lower:
            continue
        if bin_spec.upper is None or magnitude < bin_spec.upper:
            return index
    return None


def _score_fold(
    *,
    observed_counts: np.ndarray,
    model_rates: np.ndarray,
    reference_rates: np.ndarray,
    predicted_probability: np.ndarray,
    cell_ids: np.ndarray,
    bin_indices: np.ndarray,
    rng: Generator,
    policy: WalkForwardPolicy,
) -> dict[str, Any]:
    observed_binary = (observed_counts >= 1).astype(int)

    scores: dict[str, Any] = {
        "log_loss": scoring.binary_log_loss(observed_binary, predicted_probability),
        "brier_score": scoring.brier_score(observed_binary, predicted_probability),
        "point_process_log_likelihood": scoring.poisson_log_likelihood(
            observed_counts, model_rates
        ),
        "deviance": scoring.poisson_deviance(observed_counts, model_rates),
        "predictive_coverage": scoring.predictive_coverage(
            observed_counts, model_rates, coverage_level=policy.predictive_coverage_level
        ),
        "information_gain_per_event": scoring.information_gain_per_event(
            observed_counts, model_rates, reference_rates
        ),
        "pr_auc": scoring.average_precision(observed_binary, predicted_probability),
        "roc_auc": scoring.roc_auc(observed_binary, predicted_probability),
    }

    reliability = scoring.reliability_curve(
        observed_binary, predicted_probability, bin_count=policy.reliability_bin_count
    )
    scores["reliability_expected_calibration_error"] = reliability.expected_calibration_error
    scores["reliability_bins"] = [
        {
            "predicted_probability_mean": b.predicted_probability_mean,
            "observed_frequency": b.observed_frequency,
            "count": b.count,
        }
        for b in reliability.bins
    ]

    threshold_results = []
    for threshold in policy.decision_thresholds:
        ts = scoring.threshold_scores(observed_binary, predicted_probability, threshold=threshold)
        threshold_results.append(
            {
                "threshold": ts.threshold,
                "precision": ts.precision,
                "recall": ts.recall,
                "false_alarm_rate": ts.false_alarm_rate,
                "f1": ts.f1,
            }
        )
    scores["threshold_scores"] = threshold_results

    number_result = csep_tests.number_test(observed_counts, model_rates, alpha=policy.csep_alpha)
    scores["number_test"] = {
        "observed_count": number_result.observed_count,
        "forecast_count": number_result.forecast_count,
        "delta1": number_result.delta1,
        "delta2": number_result.delta2,
        "consistent_at_alpha": number_result.consistent_at_alpha,
    }

    likelihood_result = csep_tests.likelihood_test(
        observed_counts,
        model_rates,
        rng=rng,
        n_simulations=policy.n_simulations,
        alpha=policy.csep_alpha,
    )
    scores["likelihood_test"] = {
        "observed_log_likelihood": likelihood_result.observed_log_likelihood,
        "quantile": likelihood_result.quantile,
        "consistent_at_alpha": likelihood_result.consistent_at_alpha,
    }

    unique_cells = sorted(set(cell_ids.tolist()))
    cell_totals = np.array([float(np.sum(observed_counts[cell_ids == c])) for c in unique_cells])
    cell_rate_totals = np.array([float(np.sum(model_rates[cell_ids == c])) for c in unique_cells])
    spatial_result = csep_tests.spatial_test(
        cell_totals,
        cell_rate_totals,
        rng=rng,
        n_simulations=policy.n_simulations,
        alpha=policy.csep_alpha,
    )
    scores["spatial_test"] = (
        None
        if spatial_result is None
        else {
            "quantile": spatial_result.quantile,
            "consistent_at_alpha": spatial_result.consistent_at_alpha,
        }
    )

    unique_bins = sorted(set(bin_indices.tolist()))
    bin_totals = np.array([float(np.sum(observed_counts[bin_indices == b])) for b in unique_bins])
    bin_rate_totals = np.array([float(np.sum(model_rates[bin_indices == b])) for b in unique_bins])
    magnitude_result = csep_tests.magnitude_test(
        bin_totals,
        bin_rate_totals,
        rng=rng,
        n_simulations=policy.n_simulations,
        alpha=policy.csep_alpha,
    )
    scores["magnitude_test"] = (
        None
        if magnitude_result is None
        else {
            "quantile": magnitude_result.quantile,
            "consistent_at_alpha": magnitude_result.consistent_at_alpha,
        }
    )

    return scores


def _run_one_fold(
    session: Session,
    *,
    evaluation_run_id: uuid.UUID,
    forecast_service: ForecastService,
    grid: SpatialGrid,
    specification: ForecastSpecification,
    spatiotemporal_etas_estimate_id: uuid.UUID,
    gutenberg_richter_estimate_id: uuid.UUID,
    issued_at: datetime,
    horizon_id: str,
    adjudication_delay: timedelta,
    rng: Generator,
    policy: WalkForwardPolicy,
) -> EvaluationFoldScore:
    # prepare_generation_inputs is called here (for the baseline model
    # below) and again inside issue_forecast (for the real, persisted
    # forecast) -- two independent availability-safe catalog reads at the
    # same `issued_at`, rather than threading one shared result through
    # ForecastService's public API. Nothing writes to the source catalog
    # between them, so both reads are guaranteed identical; the extra
    # query is cheap relative to the O(events x cells) triggering-kernel
    # evaluation `generate_forecast_cells` does per call.
    inputs = forecast_service.prepare_generation_inputs(
        spatiotemporal_etas_estimate_id=spatiotemporal_etas_estimate_id,
        gutenberg_richter_estimate_id=gutenberg_richter_estimate_id,
        issued_at=issued_at,
        horizon_id=horizon_id,
    )
    run = forecast_service.issue_forecast(
        spatiotemporal_etas_estimate_id=spatiotemporal_etas_estimate_id,
        gutenberg_richter_estimate_id=gutenberg_richter_estimate_id,
        issued_at=issued_at,
        horizon_id=horizon_id,
        trigger_type="scheduled",
    )

    # Homogeneous-Poisson reference model for information_gain_per_event:
    # the same already-fit ETAS parameters with triggering switched off
    # (k0 = 0), background-only -- stage 1 of the scientific progression,
    # computed here purely for comparison and never persisted as a
    # ForecastRun (it is not a real forecast product).
    baseline_etas_parameters = replace(inputs.etas_parameters, k0=0.0)
    baseline_result = generate_forecast_cells(
        prior_event_times_days=inputs.prior_event_times_days,
        prior_event_latitudes=inputs.prior_event_latitudes,
        prior_event_longitudes=inputs.prior_event_longitudes,
        prior_event_magnitudes=inputs.prior_event_magnitudes,
        etas_parameters=baseline_etas_parameters,
        b_value=inputs.b_value,
        reference_magnitude=inputs.reference_magnitude,
        region_area_km2=inputs.region_area_km2,
        validity_start_days=inputs.validity_start_days,
        validity_end_days=inputs.validity_end_days,
        cells=inputs.cell_targets,
        magnitude_bins=inputs.magnitude_bins,
        policy=forecast_service.policy,
    )
    baseline_by_key = {
        (cf.cell_id, cf.magnitude_lower): cf.expected_count for cf in baseline_result.cell_forecasts
    }

    forecast_rows = list(
        session.scalars(
            select(ForecastCellMagnitudeBin).where(
                ForecastCellMagnitudeBin.forecast_run_id == run.id
            )
        )
    )
    estimable_rows = [row for row in forecast_rows if row.support_state == "estimable"]
    excluded_not_estimable_count = len(forecast_rows) - len(estimable_rows)

    adjudicated_as_of = run.validity_end + adjudication_delay
    observations = fetch_declustering_catalog(
        session,
        as_of=adjudicated_as_of,
        start_time=run.validity_start,
        end_time=run.validity_end,
        magnitude_type=inputs.completeness_source.magnitude_type,
        minimum_magnitude=inputs.reference_magnitude,
        min_latitude=inputs.completeness_source.min_latitude,
        max_latitude=inputs.completeness_source.max_latitude,
        min_longitude=inputs.completeness_source.min_longitude,
        max_longitude=inputs.completeness_source.max_longitude,
    )

    observed_counts_by_key: dict[tuple[str, float], int] = {}
    total_observed = 0
    for observation in observations:
        cell_id = _cell_id_for_point(grid, observation.latitude, observation.longitude)
        bin_index = _magnitude_bin_index(observation.magnitude, specification.magnitude_bins)
        if cell_id is None or bin_index is None:
            continue
        magnitude_lower = specification.magnitude_bins[bin_index].lower
        key = (cell_id, magnitude_lower)
        observed_counts_by_key[key] = observed_counts_by_key.get(key, 0) + 1
        total_observed += 1

    bin_index_by_lower = {
        bin_spec.lower: index for index, bin_spec in enumerate(specification.magnitude_bins)
    }

    observed_counts = np.array(
        [
            observed_counts_by_key.get((row.cell_id, row.magnitude_lower), 0)
            for row in estimable_rows
        ],
        dtype=float,
    )
    model_rates = np.array([row.expected_count for row in estimable_rows], dtype=float)
    reference_rates = np.array(
        [baseline_by_key.get((row.cell_id, row.magnitude_lower), 0.0) for row in estimable_rows],
        dtype=float,
    )
    predicted_probability = np.array(
        [row.probability_at_least_one for row in estimable_rows], dtype=float
    )
    cell_ids = np.array([row.cell_id for row in estimable_rows])
    bin_indices = np.array([bin_index_by_lower[row.magnitude_lower] for row in estimable_rows])

    scores = _score_fold(
        observed_counts=observed_counts,
        model_rates=model_rates,
        reference_rates=reference_rates,
        predicted_probability=predicted_probability,
        cell_ids=cell_ids,
        bin_indices=bin_indices,
        rng=rng,
        policy=policy,
    )

    fold_score = EvaluationFoldScore(
        evaluation_run_id=evaluation_run_id,
        forecast_run_id=run.id,
        issued_at=issued_at,
        validity_start=run.validity_start,
        validity_end=run.validity_end,
        observed_event_count=total_observed,
        excluded_not_estimable_count=excluded_not_estimable_count,
        scores_json=scores,
    )
    session.add(fold_score)
    session.flush()
    return fold_score


def _time_block_bootstrap(
    values: Sequence[float], *, rng: Generator, n_resamples: int, confidence_level: float
) -> dict[str, float] | None:
    """Bootstrap over folds. Each walk-forward fold already spans a
    distinct, non-overlapping (embargoed) time block by construction, so
    resampling folds with replacement is exactly the 'time' block
    bootstrap config/evaluation-protocol.yaml registers -- no separate
    block-partitioning step is needed. `None` when fewer than two folds
    have a defined value for this score (nothing to resample).
    """
    finite = [v for v in values if v is not None]
    if len(finite) < 2:
        return None
    array = np.asarray(finite, dtype=float)
    resample_means = rng.choice(array, size=(n_resamples, len(array)), replace=True).mean(axis=1)
    alpha = 1.0 - confidence_level
    lower = float(np.percentile(resample_means, 100 * alpha / 2.0))
    upper = float(np.percentile(resample_means, 100 * (1.0 - alpha / 2.0)))
    return {
        "point_estimate": float(array.mean()),
        "lower": lower,
        "upper": upper,
        "confidence_level": confidence_level,
        "n_folds": len(finite),
    }


_BOOTSTRAPPED_SCALAR_SCORES = (
    "log_loss",
    "brier_score",
    "point_process_log_likelihood",
    "deviance",
    "predictive_coverage",
    "information_gain_per_event",
    "pr_auc",
    "roc_auc",
    "reliability_expected_calibration_error",
)


def run_walk_forward_evaluation(
    session: Session,
    *,
    specification: ForecastSpecification,
    spatiotemporal_etas_estimate_id: uuid.UUID,
    gutenberg_richter_estimate_id: uuid.UUID,
    walk_forward_start: datetime,
    walk_forward_end: datetime,
    step: timedelta,
    horizon_id: str,
    adjudication_delay: timedelta,
    rng: Generator,
    forecast_policy: ForecastGenerationPolicy | None = None,
    policy: WalkForwardPolicy | None = None,
) -> EvaluationRun:
    """Issue and score one forecast per issue time in
    `[walk_forward_start, walk_forward_end)`, stepping by `step`. Per
    docs/backtesting.md, `adjudication_delay` should be at least the
    horizon (the embargo) so a fold's own forecast never leaks into what
    it is scored against; this is the caller's declared policy choice, not
    something this function infers or defaults silently.
    """
    if walk_forward_start.tzinfo is None or walk_forward_end.tzinfo is None:
        raise ValueError("walk_forward_start and walk_forward_end must be timezone-aware")
    if walk_forward_start >= walk_forward_end:
        raise ValueError("walk_forward_start must be before walk_forward_end")
    if step.total_seconds() <= 0:
        raise ValueError("step must be positive")

    policy = policy or WalkForwardPolicy()
    forecast_service = ForecastService(
        session, specification=specification, policy=forecast_policy or ForecastGenerationPolicy()
    )
    grid = session.get(SpatialGrid, specification.grid_id)
    if grid is None:
        raise ValueError(f"grid {specification.grid_id} not found")

    # Created up front (with placeholder aggregate fields, filled in once
    # every fold has scored) so each EvaluationFoldScore has a real,
    # non-null evaluation_run_id to cite from the moment it is persisted.
    evaluation_run = EvaluationRun(
        spatiotemporal_etas_estimate_id=spatiotemporal_etas_estimate_id,
        gutenberg_richter_estimate_id=gutenberg_richter_estimate_id,
        grid_id=grid.id,
        horizon_id=horizon_id,
        walk_forward_start=walk_forward_start,
        walk_forward_end=walk_forward_end,
        step_seconds=step.total_seconds(),
        adjudication_delay_seconds=adjudication_delay.total_seconds(),
        csep_alpha=policy.csep_alpha,
        n_simulations=policy.n_simulations,
        bootstrap_resamples=policy.bootstrap_resamples,
        bootstrap_confidence_level=policy.bootstrap_confidence_level,
        method_version=policy.method_version,
        status=policy.status,
        fold_count=0,
        zero_observed_fold_count=0,
        aggregate_scores_json={},
        diagnostics_json={},
    )
    session.add(evaluation_run)
    session.flush()

    fold_scores: list[EvaluationFoldScore] = []
    issue_time = walk_forward_start
    while issue_time < walk_forward_end:
        fold_scores.append(
            _run_one_fold(
                session,
                evaluation_run_id=evaluation_run.id,
                forecast_service=forecast_service,
                grid=grid,
                specification=specification,
                spatiotemporal_etas_estimate_id=spatiotemporal_etas_estimate_id,
                gutenberg_richter_estimate_id=gutenberg_richter_estimate_id,
                issued_at=issue_time,
                horizon_id=horizon_id,
                adjudication_delay=adjudication_delay,
                rng=rng,
                policy=policy,
            )
        )
        issue_time += step

    zero_observed_fold_count = sum(1 for fold in fold_scores if fold.observed_event_count == 0)

    aggregate_scores: dict[str, Any] = {}
    for score_name in _BOOTSTRAPPED_SCALAR_SCORES:
        values = [fold.scores_json.get(score_name) for fold in fold_scores]
        aggregate_scores[score_name] = _time_block_bootstrap(
            values,
            rng=rng,
            n_resamples=policy.bootstrap_resamples,
            confidence_level=policy.bootstrap_confidence_level,
        )

    # N-test has no single "quantile" (it reports a two-sided delta1/delta2
    # pair instead), so it is summarized separately from the three
    # simulation-based tests, which do share one quantile field.
    number_test_results = [fold.scores_json["number_test"] for fold in fold_scores]
    aggregate_scores["number_test"] = {
        "fold_count": len(number_test_results),
        "fraction_consistent_at_alpha": float(
            np.mean([r["consistent_at_alpha"] for r in number_test_results])
        ),
        "mean_delta1": float(np.mean([r["delta1"] for r in number_test_results])),
        "mean_delta2": float(np.mean([r["delta2"] for r in number_test_results])),
    }

    for test_name in ("likelihood_test", "spatial_test", "magnitude_test"):
        results = [fold.scores_json.get(test_name) for fold in fold_scores]
        defined = [r for r in results if r is not None]
        aggregate_scores[test_name] = {
            "fold_count_estimable": len(defined),
            "fraction_consistent_at_alpha": (
                float(np.mean([r["consistent_at_alpha"] for r in defined])) if defined else None
            ),
            "mean_quantile": (
                float(np.mean([r["quantile"] for r in defined])) if defined else None
            ),
        }

    evaluation_run.fold_count = len(fold_scores)
    evaluation_run.zero_observed_fold_count = zero_observed_fold_count
    evaluation_run.aggregate_scores_json = aggregate_scores
    evaluation_run.diagnostics_json = {
        "resampling_method": "block_bootstrap",
        "resampling_block_unit": "time",
        "resampling_block_definition": (
            "each walk-forward fold is one non-overlapping time block by "
            "construction; earthquake_sequence-block resampling "
            "(config/evaluation-protocol.yaml) is not implemented yet"
        ),
    }
    session.add(evaluation_run)
    session.commit()
    return evaluation_run
