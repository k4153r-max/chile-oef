from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ForecastHorizon:
    id: str
    seconds: float


@dataclass(frozen=True)
class MagnitudeBin:
    lower: float
    upper: float | None
    status: str = "active"

    @property
    def is_open_ended(self) -> bool:
        return self.upper is None


@dataclass(frozen=True)
class ForecastSpecification:
    version: int
    status: str
    grid_id: str
    horizons: tuple[ForecastHorizon, ...]
    magnitude_bins: tuple[MagnitudeBin, ...]
    reject_threshold_below_mc: bool
    stale_data_action: str

    def horizon(self, horizon_id: str) -> ForecastHorizon:
        for horizon in self.horizons:
            if horizon.id == horizon_id:
                return horizon
        raise ValueError(
            f"unknown horizon id {horizon_id!r}; registered: {[h.id for h in self.horizons]}"
        )


def load_forecast_specification(path: Path) -> ForecastSpecification:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    horizons = tuple(
        ForecastHorizon(id=entry["id"], seconds=float(entry["seconds"]))
        for entry in document["horizons"]
    )
    magnitude_bins = tuple(
        MagnitudeBin(
            lower=float(entry["lower"]),
            upper=(float(entry["upper"]) if entry.get("upper") is not None else None),
            status=entry.get("status", "active"),
        )
        for entry in document["magnitude_bins"]
    )
    estimability = document.get("estimability", {})
    return ForecastSpecification(
        version=document["version"],
        status=document["status"],
        grid_id=document["grid"]["id"],
        horizons=horizons,
        magnitude_bins=magnitude_bins,
        reject_threshold_below_mc=bool(estimability.get("reject_threshold_below_mc", True)),
        stale_data_action=estimability.get("stale_data_action", "not_estimable"),
    )
