import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import telegram_alert  # noqa: E402


def _usgs_feature(event_id: str, mag: float, when: datetime) -> dict:
    return {
        "id": event_id,
        "properties": {
            "mag": mag,
            "place": "test place",
            "time": int(when.timestamp() * 1000),
        },
        "geometry": {"type": "Point", "coordinates": [-70.0, -30.0, 10.0]},
    }


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_and_notify_ignores_events_older_than_the_time_window(monkeypatch, tmp_path):
    """Un sismo de hace 3 semanas no debe tratarse como 'nuevo' solo porque
    nunca se guardó en notified_events.json -- este es exactamente el bug
    reportado (@chile_oef avisando sismos del 24/27/31 de julio el 18 de
    agosto)."""
    old_event = _usgs_feature("old123", 5.4, datetime.now(UTC) - timedelta(days=21))
    recent_event = _usgs_feature("recent456", 5.1, datetime.now(UTC) - timedelta(minutes=10))

    payload = json.dumps({"features": [recent_event, old_event]}).encode("utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        telegram_alert.urllib.request, "urlopen",
        lambda req, timeout=15: _FakeResponse(payload),
    )

    sent_ids = []
    monkeypatch.setattr(
        telegram_alert, "send_telegram_message",
        lambda token, chat_id, msg: (sent_ids.append(msg) or True),
    )

    sent_count = telegram_alert.fetch_and_notify_new_events("x", "y", min_mag=5.0)

    assert sent_count == 1
    assert len(sent_ids) == 1
    assert "old123" not in str(sent_ids)
