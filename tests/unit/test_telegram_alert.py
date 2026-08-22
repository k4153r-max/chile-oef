import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import telegram_alert  # noqa: E402
from telegram_alert import format_observed_event_message  # noqa: E402


def _feature(event_id: str, magnitude: float, *, when: datetime | None = None) -> dict[str, object]:
    properties: dict[str, object] = {
        "mag": magnitude,
        "place": "10 km of Valparaíso, Chile",
        "url": f"https://earthquake.usgs.gov/{event_id}",
    }
    if when is not None:
        properties["time"] = int(when.timestamp() * 1000)
    return {
        "id": event_id,
        "properties": properties,
        "geometry": {"coordinates": [-71.6, -33.0, 20.0]},
    }


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._content = json.dumps(payload).encode()

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._content


def test_observed_event_message_is_factual_and_contains_source() -> None:
    message = format_observed_event_message(
        zone_name="Zona Central",
        event_mag=4.0,
        event_loc="10 km de Valparaíso",
        source_url="https://earthquake.usgs.gov/example",
        event_time=datetime(2026, 8, 22, 12, 0, tzinfo=UTC),
    )

    assert "Magnitud*: 4.0" in message
    assert "hora de Chile" in message
    assert "https://earthquake.usgs.gov/example" in message
    assert "no es una predicción" in message
    assert "Probabilidad" not in message


def test_poll_bootstraps_silently_then_sends_only_new_m4_plus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = {"features": [_feature("existing", 4.5)]}
    monkeypatch.setattr(
        telegram_alert.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(payload)
    )
    sent: list[str] = []
    monkeypatch.setattr(
        telegram_alert,
        "send_telegram_message",
        lambda _token, _chat, message: sent.append(message) or True,
    )

    assert telegram_alert.fetch_and_notify_new_events("token", "chat") == 0
    assert sent == []

    payload["features"] = [
        _feature("new-m4", 4.0),
        _feature("new-below", 3.9),
        _feature("existing", 4.5),
    ]
    assert telegram_alert.fetch_and_notify_new_events("token", "chat") == 1
    assert len(sent) == 1
    assert "Magnitud*: 4.0" in sent[0]
    assert json.loads((tmp_path / "data" / "notified_events.json").read_text()) == [
        "existing",
        "new-below",
        "new-m4",
    ]


def test_poll_ignores_events_older_than_the_time_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "notified_events.json").write_text("[]")
    payload = {
        "features": [
            _feature("recent", 4.1, when=datetime.now(UTC) - timedelta(minutes=10)),
            _feature("old", 5.4, when=datetime.now(UTC) - timedelta(days=21)),
        ]
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        telegram_alert.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(payload)
    )
    sent: list[str] = []
    monkeypatch.setattr(
        telegram_alert,
        "send_telegram_message",
        lambda _token, _chat, message: sent.append(message) or True,
    )

    assert telegram_alert.fetch_and_notify_new_events("token", "chat") == 1
    assert len(sent) == 1
    assert "Magnitud*: 4.1" in sent[0]
    assert "old" not in sent[0]
