import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.ingestion.base import FetchedArtifact

UTC_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$")
DEPTH = re.compile(r"^(-?\d+(?:\.\d+)?)\s*km$", re.IGNORECASE)
MAGNITUDE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*([A-Za-z]+)?$")
REPORT_ID = re.compile(r"/(\d+)\.html$")


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[list[str], list[str]]] = []
        self._row: list[str] | None = None
        self._links: list[str] = []
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "tr":
            self._row = []
            self._links = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append("\n")
        elif tag == "a" and self._row is not None and attrs_dict.get("href"):
            self._links.append(str(attrs_dict["href"]))

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            text = " ".join("".join(self._cell_parts).split())
            self._row.append(text)
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            self.rows.append((self._row, self._links))
            self._row = None
            self._links = []


class CsnDailyAdapter:
    source_id = "csn_daily"
    parser_version = "csn-daily-html-v1"
    base_url = "https://www.sismologia.cl"

    def __init__(
        self,
        day: date,
        *,
        timeout_seconds: float = 30.0,
        user_agent: str = "CHILE-OEF/0.1 research-platform",
    ) -> None:
        self.day = day
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.url = f"{self.base_url}/sismicidad/catalogo/{day:%Y}/{day:%m}/{day:%Y%m%d}.html"

    async def fetch(self) -> FetchedArtifact:
        retrieved_at = datetime.now(UTC)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent, "Accept": "text/html"},
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
        parser = _TableParser()
        parser.feed(artifact.content.decode("utf-8", errors="replace"))
        events: list[NormalizedEvent] = []
        for cells, links in parser.rows:
            if len(cells) < 5 or not UTC_TIME.match(cells[1]):
                continue
            coordinate_tokens = cells[2].split()
            if len(coordinate_tokens) != 2:
                raise ValueError(f"CSN coordinate schema changed: {cells[2]!r}")
            depth_match = DEPTH.match(cells[3])
            magnitude_match = MAGNITUDE.match(cells[4])
            if not depth_match or not magnitude_match:
                raise ValueError(f"CSN depth/magnitude schema changed: {cells[3:5]!r}")
            report_link = next((link for link in links if "/informes/" in link), None)
            report_match = REPORT_ID.search(report_link or "")
            if report_match:
                source_event_id = report_match.group(1)
            else:
                source_event_id = (
                    "csn-"
                    + re.sub(r"\D", "", cells[1])
                    + "-"
                    + "-".join(
                        token.replace(".", "p").replace("-", "m") for token in coordinate_tokens
                    )
                )
            local_and_place = cells[0]
            local_time_prefix = local_and_place[:19]
            place = local_and_place[19:].strip() or None
            payload = {
                "cells": cells,
                "report_url": urljoin(self.base_url, report_link) if report_link else None,
                "local_time_text": local_time_prefix,
            }
            events.append(
                NormalizedEvent(
                    source_id=self.source_id,
                    source_event_id=source_event_id,
                    event_time=datetime.strptime(cells[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC),
                    source_updated_at=None,
                    received_at=artifact.retrieved_at,
                    available_at=artifact.retrieved_at,
                    latitude=float(coordinate_tokens[0]),
                    longitude=float(coordinate_tokens[1]),
                    depth_km=float(depth_match.group(1)),
                    magnitude=float(magnitude_match.group(1)),
                    magnitude_type=magnitude_match.group(2),
                    place=place,
                    status=None,
                    source_payload=payload,
                    parser_version=self.parser_version,
                )
            )
        if not events:
            raise ValueError("CSN daily page contained no parseable event rows")
        return events
