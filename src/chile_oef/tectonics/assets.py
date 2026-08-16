import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from chile_oef.db.models import (
    CatalogSource,
    IngestionArtifact,
    IngestionRun,
    RawArtifact,
    TectonicAsset,
    TectonicRelease,
)
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.tectonics.registry import TectonicAssetSpec, TectonicReleaseSpec


class TectonicAssetService:
    def __init__(
        self,
        session: Session,
        archive: RawArchive,
        *,
        timeout_seconds: float = 120.0,
        user_agent: str = "CHILE-OEF/0.1 research-platform",
    ) -> None:
        self.session = session
        self.archive = archive
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    @staticmethod
    def _retryable_download_error(exception: BaseException) -> bool:
        if isinstance(exception, httpx.TransportError):
            return True
        if isinstance(exception, httpx.HTTPStatusError):
            return exception.response.status_code in {408, 429} or (
                500 <= exception.response.status_code < 600
            )
        return False

    async def _download(self, url: str) -> httpx.Response:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        ) as client:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(4),
                wait=wait_exponential(multiplier=0.5, max=8),
                retry=retry_if_exception(self._retryable_download_error),
                reraise=True,
            ):
                with attempt:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response
        raise RuntimeError("download retry loop ended without a response")

    def ensure_release(self, spec: TectonicReleaseSpec) -> TectonicRelease:
        if self.session.get(CatalogSource, spec.source_id) is None:
            raise ValueError(f"tectonic source {spec.source_id!r} is not registered")
        release = self.session.scalar(
            select(TectonicRelease).where(
                TectonicRelease.source_id == spec.source_id,
                TectonicRelease.release_id == spec.release_id,
            )
        )
        if release is None:
            release = TectonicRelease(
                source_id=spec.source_id,
                release_id=spec.release_id,
                title=spec.title,
                doi=spec.doi,
                license_id=spec.license,
                status="building",
                metadata_json={
                    "registry_id": spec.id,
                    "parser": spec.parser,
                },
            )
            self.session.add(release)
            self.session.commit()
        return release

    def _existing_content(
        self,
        release: TectonicRelease,
        spec: TectonicAssetSpec,
    ) -> bytes | None:
        existing = self.session.scalar(
            select(TectonicAsset).where(
                TectonicAsset.release_id == release.id,
                TectonicAsset.asset_type == spec.type,
            )
        )
        if existing is None:
            return None
        raw = self.session.get(RawArtifact, existing.raw_artifact_id)
        if raw is None:
            raise RuntimeError("tectonic asset points to a missing raw artifact")
        content = self._read_local_uri(raw.storage_uri)
        self._verify_content(spec, content)
        return content

    @staticmethod
    def _verify_content(spec: TectonicAssetSpec, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != spec.byte_length:
            raise ValueError(f"asset {spec.filename} length {len(content)} != {spec.byte_length}")
        if digest != spec.sha256:
            raise ValueError(f"asset {spec.filename} failed SHA-256 verification")
        return digest

    def _record_asset(
        self,
        *,
        run: IngestionRun,
        release: TectonicRelease,
        spec: TectonicAssetSpec,
        parser_version: str,
        artifact: FetchedArtifact,
        acquisition_mode: str,
    ) -> bytes:
        content = artifact.content
        digest = self._verify_content(spec, content)
        stored = self.archive.store(artifact, suffix=Path(spec.filename).suffix)
        raw = self.session.scalar(
            select(RawArtifact).where(
                RawArtifact.source_id == release.source_id,
                RawArtifact.sha256 == digest,
            )
        )
        if raw is None:
            raw = RawArtifact(
                source_id=release.source_id,
                retrieved_at=artifact.retrieved_at,
                source_url=artifact.source_url,
                storage_uri=stored.storage_uri,
                sha256=digest,
                byte_length=len(content),
                media_type=artifact.media_type,
                http_status=artifact.http_status,
                response_headers=artifact.response_headers,
            )
            self.session.add(raw)
            self.session.flush()
        self.session.add(
            IngestionArtifact(
                ingestion_run_id=run.id,
                raw_artifact_id=raw.id,
            )
        )
        self.session.add(
            TectonicAsset(
                release_id=release.id,
                raw_artifact_id=raw.id,
                asset_type=spec.type,
                parser_version=parser_version,
                metadata_json={
                    "filename": spec.filename,
                    "expected_sha256": spec.sha256,
                    "expected_byte_length": spec.byte_length,
                    "acquisition_mode": acquisition_mode,
                },
            )
        )
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.records_seen = 1
        self.session.commit()
        return content

    def _mark_failed(self, run_id: object, exception: BaseException) -> None:
        self.session.rollback()
        failed_run = self.session.get(IngestionRun, run_id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.finished_at = datetime.now(UTC)
            failed_run.error_message = str(exception)[:4000]
            self.session.commit()

    async def obtain(
        self,
        release: TectonicRelease,
        spec: TectonicAssetSpec,
        *,
        parser_version: str,
    ) -> bytes:
        existing = self._existing_content(release, spec)
        if existing is not None:
            return existing

        run = IngestionRun(source_id=release.source_id, request_url=spec.url)
        self.session.add(run)
        self.session.commit()
        run_id = run.id
        try:
            retrieved_at = datetime.now(UTC)
            response = await self._download(spec.url)
            artifact = FetchedArtifact(
                source_id=release.source_id,
                source_url=str(response.url),
                retrieved_at=retrieved_at,
                content=response.content,
                media_type=response.headers.get("content-type"),
                http_status=response.status_code,
                response_headers=dict(response.headers),
            )
            return self._record_asset(
                run=run,
                release=release,
                spec=spec,
                parser_version=parser_version,
                artifact=artifact,
                acquisition_mode="http_download",
            )
        except Exception as exc:
            self._mark_failed(run_id, exc)
            raise

    def obtain_local(
        self,
        release: TectonicRelease,
        spec: TectonicAssetSpec,
        path: Path,
        *,
        parser_version: str,
    ) -> bytes:
        existing = self._existing_content(release, spec)
        if existing is not None:
            return existing
        run = IngestionRun(
            source_id=release.source_id,
            request_url=path.resolve().as_uri(),
        )
        self.session.add(run)
        self.session.commit()
        run_id = run.id
        try:
            content = path.read_bytes()
            artifact = FetchedArtifact(
                source_id=release.source_id,
                source_url=spec.url,
                retrieved_at=datetime.now(UTC),
                content=content,
                media_type="application/octet-stream",
                http_status=None,
                response_headers={"x-chile-oef-acquisition-mode": "verified_local_import"},
            )
            return self._record_asset(
                run=run,
                release=release,
                spec=spec,
                parser_version=parser_version,
                artifact=artifact,
                acquisition_mode="verified_local_import",
            )
        except Exception as exc:
            self._mark_failed(run_id, exc)
            raise

    @staticmethod
    def _read_local_uri(storage_uri: str) -> bytes:
        parsed = urlparse(storage_uri)
        if parsed.scheme != "file":
            raise ValueError("only local file raw archives are supported in Phase 2")
        return Path(unquote(parsed.path)).read_bytes()
