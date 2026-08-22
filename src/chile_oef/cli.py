import argparse
import asyncio
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
from sqlalchemy import func, select

from chile_oef.app.settings import get_settings
from chile_oef.datasets.service import DatasetVersionService
from chile_oef.db.models import EvaluationFoldScore, EvaluationRun, FaultTrace, SlabNode
from chile_oef.db.session import SessionLocal
from chile_oef.evaluation.promotion import (
    assess_model_promotion,
    paired_information_gain_bootstrap,
)
from chile_oef.evaluation.replay import WalkForwardPolicy, run_walk_forward_evaluation
from chile_oef.forecast.operations import issue_operational_forecast
from chile_oef.forecast.service import ForecastService
from chile_oef.forecast.simulation import CatalogSimulationPolicy
from chile_oef.forecast.specification import load_forecast_specification
from chile_oef.ingestion.historical_backfill import (
    BackfillBounds,
    BackfillPolicy,
    run_usgs_historical_backfill,
)
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.ingestion.sources.csn_daily import CsnDailyAdapter
from chile_oef.ingestion.sources.usgs_fdsn import UsgsFdsnAdapter
from chile_oef.ingestion.sources.usgs_geojson import UsgsGeoJsonAdapter
from chile_oef.seismicity.completeness import load_completeness_policy
from chile_oef.seismicity.service import (
    BackgroundRateService,
    CompletenessEstimationService,
    DeclusteringService,
    GutenbergRichterEstimationService,
    IasEstimationService,
    ModifiedOmoriService,
    SpatiotemporalEtasService,
    TemporalEtasService,
)
from chile_oef.tectonics.assets import TectonicAssetService
from chile_oef.tectonics.classification import load_classification_parameters
from chile_oef.tectonics.faults import FaultService
from chile_oef.tectonics.grid import GridDefinition, GridService
from chile_oef.tectonics.registry import load_tectonic_registry
from chile_oef.tectonics.service import EventClassificationService, ready_release
from chile_oef.tectonics.slab2 import SlabAssetBundle, SlabService


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include timezone, for example +00:00")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chile-oef")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sync-sources", help="sync reviewed source registry to the database")
    subparsers.add_parser("ingest-usgs-feed", help="ingest the USGS all-hour GeoJSON feed")

    fdsn = subparsers.add_parser("ingest-usgs-fdsn", help="ingest a bounded USGS FDSN slice")
    fdsn.add_argument("--start", type=_aware_datetime, required=True)
    fdsn.add_argument("--end", type=_aware_datetime, required=True)
    fdsn.add_argument("--min-magnitude", type=float)

    csn = subparsers.add_parser("ingest-csn-day", help="ingest one official CSN daily page")
    csn.add_argument("--day", type=date.fromisoformat, required=True)
    csn.add_argument(
        "--allow-disabled-source",
        action="store_true",
        help="explicitly acknowledge that the CSN HTML adapter is research-only",
    )
    dataset = subparsers.add_parser(
        "create-dataset",
        help="freeze latest source-event revisions available at an as-of time",
    )
    dataset.add_argument("--dataset-id", required=True)
    dataset.add_argument("--version", required=True)
    dataset.add_argument("--as-of", type=_aware_datetime, required=True)
    dataset.add_argument("--git-commit")
    grid = subparsers.add_parser("init-grid", help="create a deterministic regular grid")
    grid.add_argument("--grid-id", default="chile_regular_0_1_v1")
    grid.add_argument("--resolution", type=Decimal, default=Decimal("0.1"))
    grid.add_argument("--min-latitude", type=Decimal, default=Decimal("-60"))
    grid.add_argument("--max-latitude", type=Decimal, default=Decimal("-15"))
    grid.add_argument("--min-longitude", type=Decimal, default=Decimal("-82"))
    grid.add_argument("--max-longitude", type=Decimal, default=Decimal("-62"))

    slab = subparsers.add_parser(
        "ingest-slab2",
        help="fetch, verify, and load pinned Slab2 assets",
    )
    slab.add_argument(
        "--asset-dir",
        type=Path,
        help="offline directory containing the exact pinned filenames; hashes remain mandatory",
    )
    subparsers.add_parser("ingest-chaf", help="fetch, verify, and load pinned CHAF faults")
    classify = subparsers.add_parser(
        "classify-tectonics",
        help="classify pending event revisions with ready pinned releases",
    )
    classify.add_argument("--limit", type=int, default=1000)

    completeness = subparsers.add_parser(
        "estimate-completeness",
        help="diagnostic maximum-curvature Mc over an availability-safe catalog window",
    )
    completeness.add_argument("--start", type=_aware_datetime, required=True)
    completeness.add_argument("--end", type=_aware_datetime, required=True)
    completeness.add_argument("--as-of", type=_aware_datetime, required=True)
    completeness.add_argument("--magnitude-type", required=True)
    completeness.add_argument(
        "--method",
        choices=["maximum_curvature", "goodness_of_fit", "entire_magnitude_range"],
        default="maximum_curvature",
    )
    completeness.add_argument("--min-latitude", type=float)
    completeness.add_argument("--max-latitude", type=float)
    completeness.add_argument("--min-longitude", type=float)
    completeness.add_argument("--max-longitude", type=float)

    gutenberg_richter = subparsers.add_parser(
        "estimate-gutenberg-richter",
        help="fit the Gutenberg-Richter b-value above a specific completeness estimate's Mc",
    )
    gutenberg_richter.add_argument("--completeness-estimate-id", type=uuid.UUID, required=True)

    decluster_parser = subparsers.add_parser(
        "decluster",
        help="nearest-neighbor decluster the catalog above a Gutenberg-Richter estimate's Mc",
    )
    decluster_parser.add_argument("--gutenberg-richter-estimate-id", type=uuid.UUID, required=True)

    background_rate = subparsers.add_parser(
        "estimate-background-rate",
        help="smooth a declustering run's background subset over a grid (adaptive kernel)",
    )
    background_rate.add_argument("--declustering-run-id", type=uuid.UUID, required=True)
    background_rate.add_argument("--grid-id", required=True)

    omori = subparsers.add_parser(
        "fit-modified-omori",
        help="fit Modified Omori-Utsu sequences for every aftershock family in a declustering run",
    )
    omori.add_argument("--declustering-run-id", type=uuid.UUID, required=True)

    etas = subparsers.add_parser(
        "fit-temporal-etas",
        help="fit temporal ETAS above a completeness estimate's Mc",
    )
    etas.add_argument("--completeness-estimate-id", type=uuid.UUID, required=True)
    etas.add_argument(
        "--declustering-run-id",
        type=uuid.UUID,
        help="optional: seed the optimizer from this run's Modified Omori families",
    )

    st_etas = subparsers.add_parser(
        "fit-spatiotemporal-etas",
        help="fit spatiotemporal ETAS above a completeness estimate's Mc (requires a bounding box)",
    )
    st_etas.add_argument("--completeness-estimate-id", type=uuid.UUID, required=True)
    st_etas.add_argument(
        "--declustering-run-id",
        type=uuid.UUID,
        help="optional: seed the optimizer's (c, p) from this run's Modified Omori families",
    )

    ias = subparsers.add_parser(
        "estimate-ias",
        help="evaluate the seismic anomaly index (IAS) against a specific temporal ETAS fit",
    )
    ias.add_argument("--temporal-etas-estimate-id", type=uuid.UUID, required=True)
    ias.add_argument("--evaluation-end-at", type=_aware_datetime, required=True)

    forecast = subparsers.add_parser(
        "issue-forecast",
        help="issue a grid-cell x magnitude-bin forecast from a spatiotemporal ETAS + GR fit",
    )
    forecast.add_argument("--spatiotemporal-etas-estimate-id", type=uuid.UUID, required=True)
    forecast.add_argument("--gutenberg-richter-estimate-id", type=uuid.UUID, required=True)
    forecast.add_argument("--background-rate-run-id", type=uuid.UUID)
    forecast.add_argument("--issued-at", type=_aware_datetime, required=True)
    forecast.add_argument("--horizon-id", required=True, help="e.g. PT6H, P1D, P3D, P7D")
    forecast.add_argument("--trigger-type", default="scheduled")
    forecast.add_argument("--supersedes-forecast-run-id", type=uuid.UUID)
    forecast.add_argument("--catalog-simulations", type=int, default=500)

    operational_forecast = subparsers.add_parser(
        "issue-operational-forecast",
        help="idempotently issue a scheduled forecast from the latest compatible model lineage",
    )
    operational_forecast.add_argument("--issued-at", type=_aware_datetime, required=True)
    operational_forecast.add_argument(
        "--horizon-id", required=True, help="e.g. PT6H, P1D, P3D, P7D"
    )
    operational_forecast.add_argument("--catalog-simulations", type=int, default=500)

    walk_forward = subparsers.add_parser(
        "run-walk-forward-evaluation",
        help=(
            "walk-forward CSEP-style evaluation (docs/backtesting.md): issue and "
            "score one forecast per issue time across a historical window"
        ),
    )
    walk_forward.add_argument("--spatiotemporal-etas-estimate-id", type=uuid.UUID, required=True)
    walk_forward.add_argument("--gutenberg-richter-estimate-id", type=uuid.UUID, required=True)
    walk_forward.add_argument(
        "--background-rate-run-id",
        type=uuid.UUID,
        help="optional adaptive spatial background candidate to evaluate",
    )
    walk_forward.add_argument("--walk-forward-start", type=_aware_datetime, required=True)
    walk_forward.add_argument("--walk-forward-end", type=_aware_datetime, required=True)
    walk_forward.add_argument("--step-seconds", type=float, required=True)
    walk_forward.add_argument("--horizon-id", required=True, help="e.g. PT6H, P1D, P3D, P7D")
    walk_forward.add_argument(
        "--adjudication-delay-seconds",
        type=float,
        required=True,
        help="catalog-maturation embargo added after each fold's validity_end before scoring",
    )
    walk_forward.add_argument("--n-simulations", type=int, default=1000)
    walk_forward.add_argument("--csep-alpha", type=float, default=0.05)
    walk_forward.add_argument("--bootstrap-resamples", type=int, default=2000)
    walk_forward.add_argument("--bootstrap-confidence-level", type=float, default=0.90)
    walk_forward.add_argument(
        "--decision-threshold",
        type=float,
        action="append",
        dest="decision_thresholds",
        help=(
            "repeatable; a declared probability threshold for precision/recall/f1/false_alarm_rate"
        ),
    )
    walk_forward.add_argument("--seed", type=int, default=0)
    promotion = subparsers.add_parser(
        "assess-model-promotion",
        help="apply the registered conservative promotion gate to an immutable evaluation run",
    )
    promotion.add_argument("--evaluation-run-id", type=uuid.UUID, required=True)
    promotion.add_argument("--champion-evaluation-run-id", type=uuid.UUID, required=True)
    promotion.add_argument("--seed", type=int, default=0)

    backfill = subparsers.add_parser(
        "backfill-usgs-historical",
        help=(
            "resumable bulk USGS FDSN ingestion over a long time range, "
            "auto-partitioned below the 20,000-result cap"
        ),
    )
    backfill.add_argument("--start", type=_aware_datetime, required=True)
    backfill.add_argument("--end", type=_aware_datetime, required=True)
    backfill.add_argument("--min-magnitude", type=float)
    backfill.add_argument("--min-latitude", type=float, default=-60.0)
    backfill.add_argument("--max-latitude", type=float, default=-15.0)
    backfill.add_argument("--min-longitude", type=float, default=-82.0)
    backfill.add_argument("--max-longitude", type=float, default=-62.0)
    backfill.add_argument("--max-results-per-slice", type=int, default=15_000)
    backfill.add_argument("--min-slice-hours", type=float, default=6.0)
    backfill.add_argument("--max-retries", type=int, default=3)
    backfill.add_argument("--retry-backoff-seconds", type=float, default=2.0)
    backfill.add_argument("--request-delay-seconds", type=float, default=1.0)
    return parser


async def _run_ingestion(adapter: object) -> None:
    settings = get_settings()
    registry = load_source_registry(settings.source_registry_path)
    source = registry.by_id(adapter.source_id)  # type: ignore[attr-defined]
    if not source.enabled and not getattr(adapter, "allow_disabled_source", False):
        raise SystemExit(
            f"source {source.id} is disabled in the reviewed registry; explicit override required"
        )
    with SessionLocal() as session:
        sync_source_registry(session, registry)
        result = await IngestionService(session, RawArchive(settings.raw_archive_path)).run(adapter)  # type: ignore[arg-type]
    print(
        f"run={result.run_id} records={result.records_seen} "
        f"new_revisions={result.revisions_inserted}"
    )


async def _ingest_slab2(asset_dir: Path | None = None) -> None:
    settings = get_settings()
    registry = load_tectonic_registry(settings.tectonic_registry_path)
    spec = registry.by_id("slab2_south_america_2018")
    with SessionLocal() as session:
        sync_source_registry(
            session,
            load_source_registry(settings.source_registry_path),
        )
        assets = TectonicAssetService(
            session,
            RawArchive(settings.raw_archive_path),
            timeout_seconds=max(settings.request_timeout_seconds, 120.0),
            user_agent=settings.user_agent,
        )
        release = assets.ensure_release(spec)
        if release.status == "ready":
            count = session.scalar(
                select(func.count()).select_from(SlabNode).where(SlabNode.release_id == release.id)
            )
            print(f"release={release.release_id} nodes={count} status=already_ready")
            return
        content: dict[str, bytes] = {}
        for asset_type in ("depth", "dip", "strike", "thickness", "uncertainty"):
            asset_spec = spec.asset(asset_type)
            content[asset_type] = (
                assets.obtain_local(
                    release,
                    asset_spec,
                    asset_dir / asset_spec.filename,
                    parser_version=spec.parser,
                )
                if asset_dir is not None
                else await assets.obtain(
                    release,
                    asset_spec,
                    parser_version=spec.parser,
                )
            )
        count = SlabService(session).load_nodes(release, SlabAssetBundle(**content))
        print(f"release={release.release_id} nodes={count} status=ready")


async def _ingest_chaf() -> None:
    settings = get_settings()
    registry = load_tectonic_registry(settings.tectonic_registry_path)
    spec = registry.by_id("chaf_2020")
    with SessionLocal() as session:
        sync_source_registry(
            session,
            load_source_registry(settings.source_registry_path),
        )
        assets = TectonicAssetService(
            session,
            RawArchive(settings.raw_archive_path),
            timeout_seconds=max(settings.request_timeout_seconds, 120.0),
            user_agent=settings.user_agent,
        )
        release = assets.ensure_release(spec)
        if release.status == "ready":
            count = session.scalar(
                select(func.count())
                .select_from(FaultTrace)
                .where(FaultTrace.release_id == release.id)
            )
            print(f"release={release.release_id} traces={count} status=already_ready")
            return
        content = await assets.obtain(
            release,
            spec.asset("faults_shapefile"),
            parser_version=spec.parser,
        )
        count = FaultService(session).load_chaf(release, content)
        print(f"release={release.release_id} traces={count} status=ready")


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    if args.command == "sync-sources":
        with SessionLocal() as session:
            sync_source_registry(session, load_source_registry(settings.source_registry_path))
        return
    if args.command == "create-dataset":
        with SessionLocal() as session:
            dataset = DatasetVersionService(session).create(
                dataset_id=args.dataset_id,
                version=args.version,
                as_of=args.as_of,
                git_commit=args.git_commit,
            )
        print(
            f"dataset={dataset.dataset_id}/{dataset.version} "
            f"manifest_sha256={dataset.manifest_sha256}"
        )
        return
    if args.command == "init-grid":
        definition = GridDefinition(
            id=args.grid_id,
            resolution_degrees=args.resolution,
            min_latitude=args.min_latitude,
            max_latitude=args.max_latitude,
            min_longitude=args.min_longitude,
            max_longitude=args.max_longitude,
        )
        with SessionLocal() as session:
            grid = GridService(session).create(definition)
        print(
            f"grid={grid.id} cells={definition.cell_count} "
            f"definition_sha256={grid.definition_sha256}"
        )
        return
    if args.command == "ingest-slab2":
        asyncio.run(_ingest_slab2(args.asset_dir))
        return
    if args.command == "ingest-chaf":
        asyncio.run(_ingest_chaf())
        return
    if args.command == "classify-tectonics":
        if args.limit < 1:
            raise SystemExit("--limit must be positive")
        with SessionLocal() as session:
            slab_release = ready_release(session, "slab2_south_america_2018")
            fault_release = ready_release(session, "chaf_2020")
            count = EventClassificationService(
                session,
                slab_release=slab_release,
                fault_release=fault_release,
                parameters=load_classification_parameters(settings.tectonic_classifier_path),
            ).classify_pending(limit=args.limit)
        print(f"classified_revisions={count}")
        return
    if args.command == "estimate-completeness":
        with SessionLocal() as session:
            service = CompletenessEstimationService(
                session,
                policy=load_completeness_policy(settings.completeness_policy_path),
            )
            estimators = {
                "maximum_curvature": service.estimate_maximum_curvature,
                "goodness_of_fit": service.estimate_goodness_of_fit,
                "entire_magnitude_range": service.estimate_entire_magnitude_range,
            }
            estimate = estimators[args.method]
            record = estimate(
                as_of=args.as_of,
                start_time=args.start,
                end_time=args.end,
                magnitude_type=args.magnitude_type,
                min_latitude=args.min_latitude,
                max_latitude=args.max_latitude,
                min_longitude=args.min_longitude,
                max_longitude=args.max_longitude,
            )
        print(
            f"method={args.method} event_count={record.event_count} "
            f"support_state={record.support_state} mc_value={record.mc_value} "
            f"role={record.role}"
        )
        return
    if args.command == "estimate-gutenberg-richter":
        with SessionLocal() as session:
            record = GutenbergRichterEstimationService(
                session,
                policy=load_completeness_policy(settings.completeness_policy_path),
            ).estimate_for_completeness_estimate(args.completeness_estimate_id)
        print(
            f"mc_used={record.mc_used} events_at_or_above_mc={record.events_at_or_above_mc} "
            f"support_state={record.support_state} b_value={record.b_value} "
            f"b_value_standard_error={record.b_value_standard_error} a_value={record.a_value}"
        )
        return
    if args.command == "decluster":
        with SessionLocal() as session:
            run = DeclusteringService(session).decluster_for_gutenberg_richter_estimate(
                args.gutenberg_richter_estimate_id
            )
        print(
            f"event_count={run.event_count} classified={run.classified_event_count} "
            f"background={run.background_event_count} "
            f"log_eta_threshold={run.log_eta_threshold}"
        )
        return
    if args.command == "estimate-background-rate":
        with SessionLocal() as session:
            background_rate_run = BackgroundRateService(session).estimate_for_declustering_run(
                args.declustering_run_id, args.grid_id
            )
        print(
            f"background_event_count={background_rate_run.background_event_count} "
            f"observation_duration_days={background_rate_run.observation_duration_days} "
            f"grid_id={background_rate_run.grid_id}"
        )
        return
    if args.command == "fit-modified-omori":
        with SessionLocal() as session:
            records = ModifiedOmoriService(session).estimate_for_declustering_run(
                args.declustering_run_id
            )
        estimable = [record for record in records if record.support_state == "estimable"]
        print(f"families={len(records)} estimable={len(estimable)}")
        return
    if args.command == "fit-temporal-etas":
        with SessionLocal() as session:
            record = TemporalEtasService(session).estimate_for_completeness_estimate(
                args.completeness_estimate_id,
                declustering_run_id=args.declustering_run_id,
            )
        print(
            f"event_count={record.event_count} support_state={record.support_state} "
            f"converged={record.converged} restarts_converged={record.restarts_converged} "
            f"mu={record.mu_per_day} k0={record.k0} alpha={record.alpha} "
            f"c={record.c_days} p={record.p_exponent}"
        )
        return
    if args.command == "fit-spatiotemporal-etas":
        with SessionLocal() as session:
            record = SpatiotemporalEtasService(session).estimate_for_completeness_estimate(
                args.completeness_estimate_id,
                declustering_run_id=args.declustering_run_id,
            )
        print(
            f"event_count={record.event_count} support_state={record.support_state} "
            f"converged={record.converged} restarts_converged={record.restarts_converged} "
            f"mu={record.mu_per_day} k0={record.k0} alpha={record.alpha} "
            f"c={record.c_days} p={record.p_exponent} d0={record.d0_km} "
            f"gamma={record.gamma} q={record.q_exponent}"
        )
        return
    if args.command == "estimate-ias":
        with SessionLocal() as session:
            record = IasEstimationService(session).estimate_for_temporal_etas_estimate(
                args.temporal_etas_estimate_id,
                evaluation_end_at=args.evaluation_end_at,
            )
        print(
            f"support_state={record.support_state} ias_score={record.ias_score} "
            f"observed={record.observed_count} expected={record.expected_count} "
            f"deviance={record.deviance} historical_windows={record.historical_window_count}"
        )
        return
    if args.command == "issue-forecast":
        with SessionLocal() as session:
            run = ForecastService(
                session,
                specification=load_forecast_specification(settings.forecast_specification_path),
                simulation_policy=CatalogSimulationPolicy(simulations=args.catalog_simulations),
            ).issue_forecast(
                spatiotemporal_etas_estimate_id=args.spatiotemporal_etas_estimate_id,
                gutenberg_richter_estimate_id=args.gutenberg_richter_estimate_id,
                issued_at=args.issued_at,
                horizon_id=args.horizon_id,
                simulation_policy=CatalogSimulationPolicy(simulations=args.catalog_simulations),
                background_rate_run_id=args.background_rate_run_id,
                trigger_type=args.trigger_type,
                supersedes_forecast_run_id=args.supersedes_forecast_run_id,
            )
        print(
            f"forecast_run_id={run.id} cells={run.cell_count} bins={run.magnitude_bin_count} "
            f"validity_start={run.validity_start} validity_end={run.validity_end}"
        )
        return
    if args.command == "issue-operational-forecast":
        with SessionLocal() as session:
            result = issue_operational_forecast(
                session,
                specification=load_forecast_specification(settings.forecast_specification_path),
                issued_at=args.issued_at,
                horizon_id=args.horizon_id,
                simulation_policy=CatalogSimulationPolicy(simulations=args.catalog_simulations),
            )
        print(
            f"forecast_run_id={result.run.id} created={result.created} "
            f"validity_start={result.run.validity_start} "
            f"validity_end={result.run.validity_end}"
        )
        return
    if args.command == "run-walk-forward-evaluation":
        with SessionLocal() as session:
            evaluation_run = run_walk_forward_evaluation(
                session,
                specification=load_forecast_specification(settings.forecast_specification_path),
                spatiotemporal_etas_estimate_id=args.spatiotemporal_etas_estimate_id,
                gutenberg_richter_estimate_id=args.gutenberg_richter_estimate_id,
                background_rate_run_id=args.background_rate_run_id,
                walk_forward_start=args.walk_forward_start,
                walk_forward_end=args.walk_forward_end,
                step=timedelta(seconds=args.step_seconds),
                horizon_id=args.horizon_id,
                adjudication_delay=timedelta(seconds=args.adjudication_delay_seconds),
                rng=np.random.default_rng(args.seed),
                policy=WalkForwardPolicy(
                    n_simulations=args.n_simulations,
                    csep_alpha=args.csep_alpha,
                    bootstrap_resamples=args.bootstrap_resamples,
                    bootstrap_confidence_level=args.bootstrap_confidence_level,
                    decision_thresholds=tuple(args.decision_thresholds or ()),
                ),
            )
        print(
            f"evaluation_run_id={evaluation_run.id} folds={evaluation_run.fold_count} "
            f"zero_observed_folds={evaluation_run.zero_observed_fold_count}"
        )
        return
    if args.command == "assess-model-promotion":
        with SessionLocal() as session:
            evaluation_run = session.get(EvaluationRun, args.evaluation_run_id)
            if evaluation_run is None:
                raise SystemExit(f"evaluation run {args.evaluation_run_id} not found")
            champion_run = session.get(EvaluationRun, args.champion_evaluation_run_id)
            if champion_run is None:
                raise SystemExit(
                    f"champion evaluation run {args.champion_evaluation_run_id} not found"
                )
            protocol_fields = (
                "grid_id",
                "horizon_id",
                "walk_forward_start",
                "walk_forward_end",
                "step_seconds",
                "adjudication_delay_seconds",
            )
            if any(
                getattr(evaluation_run, field) != getattr(champion_run, field)
                for field in protocol_fields
            ):
                raise SystemExit("candidate and champion evaluation protocols do not match")
            candidate_folds = {
                fold.issued_at: fold
                for fold in session.scalars(
                    select(EvaluationFoldScore).where(
                        EvaluationFoldScore.evaluation_run_id == evaluation_run.id
                    )
                )
            }
            champion_folds = {
                fold.issued_at: fold
                for fold in session.scalars(
                    select(EvaluationFoldScore).where(
                        EvaluationFoldScore.evaluation_run_id == champion_run.id
                    )
                )
            }
            if candidate_folds.keys() != champion_folds.keys():
                raise SystemExit("candidate and champion folds do not align exactly")
            issue_times = sorted(candidate_folds)
            observed_event_counts = [
                candidate_folds[issue_time].observed_event_count for issue_time in issue_times
            ]
            if any(
                candidate_folds[issue_time].observed_event_count
                != champion_folds[issue_time].observed_event_count
                for issue_time in issue_times
            ):
                raise SystemExit("candidate and champion were scored against different outcomes")
            comparative_gain = paired_information_gain_bootstrap(
                candidate_log_likelihoods=[
                    float(candidate_folds[t].scores_json["point_process_log_likelihood"])
                    for t in issue_times
                ],
                champion_log_likelihoods=[
                    float(champion_folds[t].scores_json["point_process_log_likelihood"])
                    for t in issue_times
                ],
                observed_event_counts=observed_event_counts,
                rng=np.random.default_rng(args.seed),
                n_resamples=evaluation_run.bootstrap_resamples,
                confidence_level=evaluation_run.bootstrap_confidence_level,
            )
            assessment = assess_model_promotion(
                aggregate_scores=evaluation_run.aggregate_scores_json,
                comparative_information_gain=comparative_gain,
                fold_count=len(issue_times),
                observed_event_count=sum(observed_event_counts),
            )
        payload = assessment.as_dict()
        payload["candidate_evaluation_run_id"] = str(evaluation_run.id)
        payload["champion_evaluation_run_id"] = str(champion_run.id)
        payload["comparative_information_gain_per_event"] = comparative_gain
        print(json.dumps(payload, sort_keys=True))
        return
    if args.command == "backfill-usgs-historical":
        bounds = BackfillBounds(
            min_latitude=args.min_latitude,
            max_latitude=args.max_latitude,
            min_longitude=args.min_longitude,
            max_longitude=args.max_longitude,
        )
        policy = BackfillPolicy(
            max_results_per_slice=args.max_results_per_slice,
            min_slice=timedelta(hours=args.min_slice_hours),
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
            request_delay_seconds=args.request_delay_seconds,
        )
        with SessionLocal() as session:
            summary = asyncio.run(
                run_usgs_historical_backfill(
                    session,
                    RawArchive(settings.raw_archive_path),
                    start_time=args.start,
                    end_time=args.end,
                    bounds=bounds,
                    min_magnitude=args.min_magnitude,
                    timeout_seconds=settings.request_timeout_seconds,
                    user_agent=settings.user_agent,
                    policy=policy,
                )
            )
        print(
            f"slices={summary.total_slices} succeeded={summary.succeeded_slices} "
            f"skipped={summary.skipped_already_done_slices} "
            f"failed={len(summary.failed_slices)} events_seen={summary.total_events_seen} "
            f"revisions_inserted={summary.total_revisions_inserted}"
        )
        for failed_start, failed_end, message in summary.failed_slices:
            print(f"  FAILED {failed_start.isoformat()}..{failed_end.isoformat()}: {message}")
        return
    if args.command == "ingest-usgs-feed":
        adapter = UsgsGeoJsonAdapter(
            timeout_seconds=settings.request_timeout_seconds, user_agent=settings.user_agent
        )
    elif args.command == "ingest-usgs-fdsn":
        adapter = UsgsFdsnAdapter(
            start_time=args.start,
            end_time=args.end,
            min_magnitude=args.min_magnitude,
            timeout_seconds=settings.request_timeout_seconds,
            user_agent=settings.user_agent,
        )
    else:
        adapter = CsnDailyAdapter(
            args.day,
            timeout_seconds=settings.request_timeout_seconds,
            user_agent=settings.user_agent,
        )
        adapter.allow_disabled_source = args.allow_disabled_source
    asyncio.run(_run_ingestion(adapter))


if __name__ == "__main__":
    main()
