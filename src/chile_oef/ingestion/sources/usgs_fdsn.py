import json
from datetime import UTC, datetime
from typing import Any

import httpx

from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.sources.usgs_geojson import UsgsGeoJsonAdapter


class UsgsFdsnAdapter(UsgsGeoJsonAdapter):
    """Bounded FDSN Event query returning GeoJSON.

    Historical orchestration must partition intervals and verify `count` before
    requesting a slice that could exceed the service's 20,000-result limit.
    """

    parser_version = "usgs-fdsn-geojson-v1"
    query_url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    count_url = "https://earthquake.usgs.gov/fdsnws/event/1/count"
    max_results = 20_000

    def __init__(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        min_latitude: float = -60,
        max_latitude: float = -15,
        min_longitude: float = -82,
        max_longitude: float = -62,
        min_magnitude: float | None = None,
        timeout_seconds: float = 60.0,
        user_agent: str = "CHILE-OEF/0.1 research-platform",
    ) -> None:
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("FDSN query times must be timezone-aware")
        if start_time >= end_time:
            raise ValueError("start_time must precede end_time")
        self.start_time = start_time.astimezone(UTC)
        self.end_time = end_time.astimezone(UTC)
        self.bounds = (min_latitude, max_latitude, min_longitude, max_longitude)
        self.min_magnitude = min_magnitude
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def query_parameters(self, *, format_name: str) -> dict[str, Any]:
        min_lat, max_lat, min_lon, max_lon = self.bounds
        params: dict[str, Any] = {
            "format": format_name,
            "starttime": self.start_time.isoformat(),
            "endtime": self.end_time.isoformat(),
            "minlatitude": min_lat,
            "maxlatitude": max_lat,
            "minlongitude": min_lon,
            "maxlongitude": max_lon,
            "orderby": "time-asc",
        }
        if self.min_magnitude is not None:
            params["minmagnitude"] = self.min_magnitude
        return params

    async def count(self) -> int:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, headers={"User-Agent": self.user_agent}
        ) as client:
            response = await client.get(
                self.count_url, params=self.query_parameters(format_name="geojson")
            )
            response.raise_for_status()
        return self.parse_count_response(response.text)

    @staticmethod
    def parse_count_response(payload: str) -> int:
        """Accept both documented plain text and observed GeoJSON count forms."""

        value = payload.strip()
        if value.startswith("{"):
            document = json.loads(value)
            count = document.get("count")
            if not isinstance(count, int):
                raise ValueError("USGS count response has no integer count")
            return count
        return int(value)

    async def fetch(self) -> FetchedArtifact:
        count = await self.count()
        if count > self.max_results:
            raise ValueError(
                f"FDSN query would return {count} events; partition below {self.max_results}"
            )
        retrieved_at = datetime.now(UTC)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent, "Accept": "application/geo+json"},
        ) as client:
            response = await client.get(
                self.query_url, params=self.query_parameters(format_name="geojson")
            )
            response.raise_for_status()
        return FetchedArtifact(
            source_id=self.source_id,
            source_url=str(response.url),
            retrieved_at=retrieved_at,
            content=response.content,
            media_type=response.headers.get("content-type"),
            http_status=response.status_code,
            response_headers=dict(response.headers),
        )
