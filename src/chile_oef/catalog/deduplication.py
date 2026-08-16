import math
from dataclasses import dataclass
from datetime import datetime

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class EventFingerprint:
    event_time: datetime
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None


@dataclass(frozen=True)
class MatchResult:
    probability: float
    time_delta_seconds: float
    distance_km: float
    magnitude_delta: float | None
    depth_delta_km: float | None
    decision: str


class DeduplicationScorer:
    """Transparent candidate scorer; it never deletes source observations."""

    version = "gaussian-linkage-v1"

    def __init__(
        self,
        *,
        time_scale_seconds: float = 30.0,
        distance_scale_km: float = 30.0,
        magnitude_scale: float = 0.5,
        depth_scale_km: float = 40.0,
        auto_match_probability: float = 0.95,
        candidate_probability: float = 0.50,
    ) -> None:
        values = (
            time_scale_seconds,
            distance_scale_km,
            magnitude_scale,
            depth_scale_km,
        )
        if any(value <= 0 for value in values):
            raise ValueError("all linkage scales must be positive")
        self.time_scale_seconds = time_scale_seconds
        self.distance_scale_km = distance_scale_km
        self.magnitude_scale = magnitude_scale
        self.depth_scale_km = depth_scale_km
        self.auto_match_probability = auto_match_probability
        self.candidate_probability = candidate_probability

    def compare(self, left: EventFingerprint, right: EventFingerprint) -> MatchResult:
        dt = abs((left.event_time - right.event_time).total_seconds())
        distance = haversine_km(left.latitude, left.longitude, right.latitude, right.longitude)
        terms = [
            (dt / self.time_scale_seconds) ** 2,
            (distance / self.distance_scale_km) ** 2,
        ]
        magnitude_delta = None
        if left.magnitude is not None and right.magnitude is not None:
            magnitude_delta = abs(left.magnitude - right.magnitude)
            terms.append((magnitude_delta / self.magnitude_scale) ** 2)
        depth_delta = None
        if left.depth_km is not None and right.depth_km is not None:
            depth_delta = abs(left.depth_km - right.depth_km)
            terms.append((depth_delta / self.depth_scale_km) ** 2)

        probability = math.exp(-0.5 * sum(terms))
        if probability >= self.auto_match_probability:
            decision = "auto_match"
        elif probability >= self.candidate_probability:
            decision = "candidate"
        else:
            decision = "distinct"
        return MatchResult(
            probability=probability,
            time_delta_seconds=dt,
            distance_km=distance,
            magnitude_delta=magnitude_delta,
            depth_delta_km=depth_delta,
            decision=decision,
        )
