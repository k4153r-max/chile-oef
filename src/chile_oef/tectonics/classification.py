import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from chile_oef.tectonics.slab2 import SlabSample


@dataclass(frozen=True)
class ClassificationParameters:
    method_version: str = "slab_residual_uncalibrated_v1"
    calibration_status: str = "uncalibrated_rule_baseline"
    interface_half_width_km: float = 10.0
    default_event_depth_uncertainty_km: float = 15.0
    default_slab_uncertainty_km: float = 10.0
    default_slab_thickness_km: float = 60.0
    maximum_crustal_depth_km: float = 50.0
    minimum_label_probability: float = 0.60


@dataclass(frozen=True)
class TectonicClassification:
    label: str
    probabilities: dict[str, float]
    slab_depth_km: float | None
    signed_vertical_residual_km: float | None
    signed_normal_distance_km: float | None
    diagnostics: dict[str, object]
    method_version: str
    calibration_status: str


def load_classification_parameters(path: Path) -> ClassificationParameters:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    keys = ClassificationParameters.__dataclass_fields__
    values = {key: document[key] for key in keys if key in document}
    return ClassificationParameters(**values)


def _normal_cdf(value: float, *, mean: float, sigma: float) -> float:
    return 0.5 * (1.0 + math.erf((value - mean) / (sigma * math.sqrt(2.0))))


def _interval_probability(lower: float, upper: float, *, mean: float, sigma: float) -> float:
    return max(
        0.0,
        _normal_cdf(upper, mean=mean, sigma=sigma) - _normal_cdf(lower, mean=mean, sigma=sigma),
    )


def classify_from_slab(
    *,
    event_depth_km: float | None,
    event_depth_uncertainty_km: float | None,
    slab: SlabSample | None,
    parameters: ClassificationParameters | None = None,
) -> TectonicClassification:
    parameters = parameters or ClassificationParameters()
    categories = ("interface", "intraslab", "crustal", "outer_rise", "volcanic", "unknown")
    if event_depth_km is None or slab is None:
        probabilities = {category: 0.0 for category in categories}
        probabilities["unknown"] = 1.0
        return TectonicClassification(
            label="unknown",
            probabilities=probabilities,
            slab_depth_km=slab.depth_km if slab else None,
            signed_vertical_residual_km=None,
            signed_normal_distance_km=None,
            diagnostics={"reason": "missing_event_depth_or_slab_coverage"},
            method_version=parameters.method_version,
            calibration_status=parameters.calibration_status,
        )

    event_sigma = max(
        event_depth_uncertainty_km
        if event_depth_uncertainty_km is not None
        else parameters.default_event_depth_uncertainty_km,
        0.1,
    )
    slab_sigma = max(
        slab.uncertainty_km
        if slab.uncertainty_km is not None
        else parameters.default_slab_uncertainty_km,
        0.1,
    )
    residual = event_depth_km - slab.depth_km
    residual_sigma = math.hypot(event_sigma, slab_sigma)
    band = parameters.interface_half_width_km
    thickness = max(
        slab.thickness_km
        if slab.thickness_km is not None
        else parameters.default_slab_thickness_km,
        band,
    )
    interface = _interval_probability(-band, band, mean=residual, sigma=residual_sigma)
    intraslab = _interval_probability(band, thickness, mean=residual, sigma=residual_sigma)
    above_slab = _normal_cdf(-band, mean=residual, sigma=residual_sigma)
    below_slab = 1.0 - _normal_cdf(thickness, mean=residual, sigma=residual_sigma)
    crustal_gate = _normal_cdf(
        parameters.maximum_crustal_depth_km,
        mean=event_depth_km,
        sigma=event_sigma,
    )
    crustal = above_slab * crustal_gate
    unknown = above_slab * (1.0 - crustal_gate) + below_slab
    raw = {
        "interface": interface,
        "intraslab": intraslab,
        "crustal": crustal,
        "outer_rise": 0.0,
        "volcanic": 0.0,
        "unknown": unknown,
    }
    total = sum(raw.values())
    probabilities = {key: value / total for key, value in raw.items()}
    candidate = max(probabilities, key=probabilities.get)  # type: ignore[arg-type]
    label = (
        candidate if probabilities[candidate] >= parameters.minimum_label_probability else "unknown"
    )
    normal_distance = (
        residual * math.cos(math.radians(slab.dip_degrees))
        if slab.dip_degrees is not None
        else None
    )
    return TectonicClassification(
        label=label,
        probabilities=probabilities,
        slab_depth_km=slab.depth_km,
        signed_vertical_residual_km=residual,
        signed_normal_distance_km=normal_distance,
        diagnostics={
            "event_depth_uncertainty_km": event_sigma,
            "event_uncertainty_assumed": event_depth_uncertainty_km is None,
            "slab_uncertainty_km": slab_sigma,
            "slab_uncertainty_assumed": slab.uncertainty_km is None,
            "combined_residual_sigma_km": residual_sigma,
            "interface_half_width_km": band,
            "slab_thickness_km": thickness,
            "slab_thickness_assumed": slab.thickness_km is None,
            "normal_distance_interpretation": (
                "local_planar_vertical_projection_not_true_3d_closest_distance"
            ),
            "chaf_used_as_probability_input": False,
            "probabilities_calibrated": False,
        },
        method_version=parameters.method_version,
        calibration_status=parameters.calibration_status,
    )
