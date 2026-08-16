from dataclasses import dataclass

from chile_oef.catalog.normalization import NormalizedEvent


@dataclass(frozen=True)
class QualityIssue:
    flag: str
    severity: str
    detail: str


KNOWN_MAGNITUDE_TYPES = {
    "m",
    "mb",
    "md",
    "ml",
    "mlv",
    "ms",
    "mw",
    "mwb",
    "mwc",
    "mwr",
    "mww",
}


def evaluate_event_quality(event: NormalizedEvent) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if event.depth_km is None:
        issues.append(QualityIssue("missing_depth", "warning", "Source omitted depth"))
    elif not -10 <= event.depth_km <= 800:
        issues.append(
            QualityIssue(
                "implausible_depth",
                "error",
                f"Depth {event.depth_km} km is outside the accepted ingest range",
            )
        )
    if event.magnitude is None:
        issues.append(QualityIssue("missing_magnitude", "warning", "Source omitted magnitude"))
    if event.magnitude_type is None or event.magnitude_type not in KNOWN_MAGNITUDE_TYPES:
        issues.append(
            QualityIssue(
                "unknown_magnitude_type",
                "warning",
                f"Unrecognized magnitude type: {event.magnitude_type!r}",
            )
        )
    if event.location_uncertainty_km is None:
        issues.append(
            QualityIssue(
                "location_uncertainty_unknown",
                "info",
                "No horizontal location uncertainty was supplied",
            )
        )
    if event.magnitude_uncertainty is None:
        issues.append(
            QualityIssue(
                "magnitude_uncertainty_unknown",
                "info",
                "No magnitude uncertainty was supplied",
            )
        )
    return issues
