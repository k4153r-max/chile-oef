from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.replay.clock import ReplayClock


@dataclass(frozen=True)
class ReplayEnvelope:
    available_at: datetime
    event: NormalizedEvent


class ReplayEngine:
    """Deterministic event replay ordered by availability, never origin time."""

    def __init__(self, clock: ReplayClock) -> None:
        self.clock = clock

    def run(
        self,
        events: Iterable[NormalizedEvent],
        consume: Callable[[NormalizedEvent, ReplayClock], None],
    ) -> int:
        ordered = sorted(events, key=lambda event: (event.available_at, event.source_event_id))
        consumed = 0
        for event in ordered:
            self.clock.advance_to(event.available_at)
            consume(event, self.clock)
            consumed += 1
        return consumed
