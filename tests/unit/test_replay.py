from datetime import UTC, datetime

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.replay.clock import ReplayClock
from chile_oef.replay.engine import ReplayEngine


def make_event(identifier: str, event_hour: int, available_hour: int) -> NormalizedEvent:
    available = datetime(2026, 1, 1, available_hour, tzinfo=UTC)
    return NormalizedEvent(
        source_id="test",
        source_event_id=identifier,
        event_time=datetime(2026, 1, 1, event_hour, tzinfo=UTC),
        received_at=available,
        available_at=available,
        latitude=-33,
        longitude=-72,
        source_payload={"id": identifier},
        parser_version="test",
    )


def test_replay_orders_by_availability_not_event_time() -> None:
    late_report = make_event("early-event", 1, 4)
    fast_report = make_event("late-event", 2, 3)
    seen: list[str] = []
    clock = ReplayClock(datetime(2026, 1, 1, tzinfo=UTC))

    count = ReplayEngine(clock).run(
        [late_report, fast_report], lambda item, _: seen.append(item.source_event_id)
    )

    assert count == 2
    assert seen == ["late-event", "early-event"]
    assert clock.current_time.hour == 4
