import json
from datetime import UTC, datetime
from typing import Any

import httpx

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.ingestion.base import FetchedArtifact


def _epoch_millis(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)


class UsgsGeoJsonAdapter:
    source_id = "usgs_comcat"
    parser_version = "usgs-geojson-v1"

    def __init__(
        self,
        *,
        url: str = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
        timeout_seconds: float = 30.0,
        user_agent: str = "CHILE-OEF/0.1 research-platform",
        min_latitude: float = -60.0,
        max_latitude: float = -15.0,
        min_longitude: float = -82.0,
        max_longitude: float = -62.0,
    ) -> None:
        if min_latitude >= max_latitude or min_longitude >= max_longitude:
            raise ValueError("invalid geographic bounds")
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.bounds = (min_latitude, max_latitude, min_longitude, max_longitude)

    async def fetch(self) -> FetchedArtifact:
        retrieved_at = datetime.now(UTC)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent, "Accept": "application/geo+json"},
        ) as client:
            response = await client.get(self.url)
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

    def parse(self, artifact: FetchedArtifact) -> list[NormalizedEvent]:
        document: dict[str, Any] = json.loads(artifact.content)
        features = document.get("features")
        if not isinstance(features, list):
            raise ValueError("USGS GeoJSON payload has no features array")
        events = [self._parse_feature(feature, artifact.retrieved_at) for feature in features]
        return [event for event in events if self._inside_bounds(event)]

    def _inside_bounds(self, event: NormalizedEvent) -> bool:
        min_lat, max_lat, min_lon, max_lon = self.bounds
        return min_lat <= event.latitude <= max_lat and min_lon <= event.longitude <= max_lon

    def _parse_feature(self, feature: dict[str, Any], received_at: datetime) -> NormalizedEvent:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            raise ValueError(f"USGS feature {feature.get('id')!r} has invalid coordinates")
        event_time = _epoch_millis(properties.get("time"))
        if event_time is None:
            raise ValueError(f"USGS feature {feature.get('id')!r} has no event time")
        source_event_id = str(feature.get("id") or "").strip()
        if not source_event_id:
            raise ValueError("USGS feature has no id")
        depth = coordinates[2] if len(coordinates) > 2 else None
        return NormalizedEvent(
            source_id=self.source_id,
            source_event_id=source_event_id,
            event_time=event_time,
            source_updated_at=_epoch_millis(properties.get("updated")),
            received_at=received_at,
            available_at=received_at,
            longitude=float(coordinates[0]),
            latitude=float(coordinates[1]),
            depth_km=float(depth) if depth is not None else None,
            magnitude=(float(properties["mag"]) if properties.get("mag") is not None else None),
            magnitude_type=properties.get("magType"),
            place=properties.get("place"),
            status=properties.get("status"),
            location_uncertainty_km=(
                float(properties["horizontalError"])
                if properties.get("horizontalError") is not None
                else None
            ),
            depth_uncertainty_km=(
                float(properties["depthError"])
                if properties.get("depthError") is not None
                else None
            ),
            magnitude_uncertainty=(
                float(properties["magError"]) if properties.get("magError") is not None else None
            ),
            source_payload=feature,
            parser_version=self.parser_version,
        )
