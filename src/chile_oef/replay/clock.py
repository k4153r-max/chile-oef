from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class ReplayClock:
    current_time: datetime

    def __post_init__(self) -> None:
        if self.current_time.tzinfo is None:
            raise ValueError("replay clock must be timezone-aware")
        self.current_time = self.current_time.astimezone(UTC)

    def advance_to(self, timestamp: datetime) -> None:
        if timestamp.tzinfo is None:
            raise ValueError("replay timestamp must be timezone-aware")
        timestamp = timestamp.astimezone(UTC)
        if timestamp < self.current_time:
            raise ValueError("replay clock cannot move backwards")
        self.current_time = timestamp
