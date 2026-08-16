import argparse
import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from chile_oef.app.settings import get_settings
from chile_oef.datasets.service import DatasetVersionService
from chile_oef.db.models import FaultTrace, SlabNode
from chile_oef.db.session import SessionLocal
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.ingestion.sources.csn_daily import CsnDailyAdapter
from chile_oef.ingestion.sources.usgs_fdsn import UsgsFdsnAdapter
from chile_oef.ingestion.sources.usgs_geojson import UsgsGeoJsonAdapter
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
