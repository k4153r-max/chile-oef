from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx
from sqlalchemy.orm import Session

from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.tectonics.assets import TectonicAssetService


def _service(tmp_path: Path) -> TectonicAssetService:
    return TectonicAssetService(
        Mock(spec=Session),
        RawArchive(tmp_path),
        timeout_seconds=1,
    )


@pytest.mark.asyncio
@respx.mock
async def test_static_asset_download_retries_transient_server_error(tmp_path: Path) -> None:
    url = "https://example.test/slab.xyz"
    route = respx.get(url).mock(
        side_effect=[
            httpx.Response(502),
            httpx.Response(200, content=b"verified later by obtain"),
        ]
    )
    response = await _service(tmp_path)._download(url)
    assert response.status_code == 200
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_static_asset_download_does_not_retry_permanent_not_found(
    tmp_path: Path,
) -> None:
    url = "https://example.test/missing.xyz"
    route = respx.get(url).mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        await _service(tmp_path)._download(url)
    assert route.call_count == 1
