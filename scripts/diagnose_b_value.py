"""Diagnose why the first real-catalog Gutenberg-Richter b-value is ~2.13.

Replicates the 2005-01-01..2015-01-01 Chile-box USGS ComCat sample used for
the first production Mc/GR fit (docs/PROJECT_STATE.md) and prints:

- Aki (1965) MLE with the same 0.1-bin Utsu correction the estimator uses;
- a Mc sweep on mb (the production magnitude type);
- the same estimator on other native magnitude types, never mixed;
- the mb histogram above 4.0, so truncation/saturation is visible.

Does not write to the database and does not change any persisted estimate.
Network access is optional: pass --from-json to reuse a saved feature list.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

USGS_QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query"
CHILE_BOUNDS = {
    "minlatitude": -60,
    "maxlatitude": -15,
    "minlongitude": -82,
    "maxlongitude": -62,
}
PRODUCTION_WINDOW = ("2005-01-01T00:00:00", "2015-01-01T00:00:00")
PRODUCTION_MC = 4.97
PRODUCTION_MAGNITUDE_TYPE = "mb"
BIN_WIDTH = 0.1


def bin_magnitude(magnitude: float, bin_width: float = BIN_WIDTH) -> float:
    return round(round(magnitude / bin_width) * bin_width, 10)


def aki_b_value(magnitudes: list[float], mc: float) -> dict | None:
    mc_binned = bin_magnitude(mc)
    events = [
        binned
        for binned in (bin_magnitude(magnitude) for magnitude in magnitudes)
        if binned >= mc_binned - 1e-9
    ]
    n = len(events)
    if n < 2:
        return None
    mean = sum(events) / n
    denominator = mean - (mc_binned - BIN_WIDTH / 2.0)
    if denominator <= 0:
        return {
            "n": n,
            "mean": mean,
            "denominator": denominator,
            "b": None,
            "se": None,
            "min": min(events),
            "max": max(events),
            "range": max(events) - mc_binned,
            "hist": dict(sorted(collections.Counter(events).items())),
        }
    b_value = math.log10(math.e) / denominator
    variance_term = sum((magnitude - mean) ** 2 for magnitude in events) / (n * (n - 1))
    standard_error = 2.30 * (b_value**2) * math.sqrt(variance_term)
    return {
        "n": n,
        "mean": mean,
        "denominator": denominator,
        "b": b_value,
        "se": standard_error,
        "min": min(events),
        "max": max(events),
        "range": max(events) - mc_binned,
        "hist": dict(sorted(collections.Counter(events).items())),
    }


def fetch_usgs() -> list[dict]:
    params = {
        "format": "geojson",
        "starttime": PRODUCTION_WINDOW[0],
        "endtime": PRODUCTION_WINDOW[1],
        "orderby": "time-asc",
        "limit": 20000,
        **CHILE_BOUNDS,
    }
    url = USGS_QUERY + "?" + urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "chile-oef-diagnose/0.1"})
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    rows = []
    for feature in payload["features"]:
        properties = feature["properties"]
        rows.append({"mag": properties.get("mag"), "type": properties.get("magType")})
    return rows


def load_rows(path: Path | None) -> list[dict]:
    if path is None:
        return fetch_usgs()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "features" in raw:
        return [
            {"mag": feature["properties"].get("mag"), "type": feature["properties"].get("magType")}
            for feature in raw["features"]
        ]
    return raw


def fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", type=Path, default=None)
    args = parser.parse_args()

    rows = load_rows(args.from_json)
    print(f"events loaded: {len(rows)}")
    types = collections.Counter(row["type"] for row in rows)
    print("magnitude types:", types.most_common())

    by_type: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        if row["mag"] is None or row["type"] is None:
            continue
        by_type[str(row["type"])].append(float(row["mag"]))

    mb = by_type.get(PRODUCTION_MAGNITUDE_TYPE, [])
    print()
    print(f"=== production slice: {PRODUCTION_MAGNITUDE_TYPE} ===")
    print(f"n={len(mb)} min={min(mb):.2f} max={max(mb):.2f}" if mb else "no mb events")
    production = aki_b_value(mb, PRODUCTION_MC)
    if production is None:
        print("Aki estimate not defined")
        return 1
    print(
        f"Mc={PRODUCTION_MC} n>={production['n']} b={fmt(production['b'])} "
        f"se={fmt(production['se'])} mean={fmt(production['mean'])} "
        f"max={fmt(production['max'], 1)} range={fmt(production['range'], 1)}"
    )
    print("histogram at/above Mc:")
    for magnitude, count in production["hist"].items():
        print(f"  {magnitude:4.1f}  {count:4d}  {'#' * max(1, count // 3)}")

    print()
    print("=== Mc sweep on mb ===")
    print(f"{'Mc':>5} {'n':>5} {'b':>6} {'se':>6} {'mean':>6} {'max':>5} {'range':>6}")
    for mc in (4.0, 4.3, 4.5, 4.7, 4.9, 4.97, 5.0, 5.2, 5.5, 5.8):
        result = aki_b_value(mb, mc)
        if result is None:
            print(f"{mc:5.2f}     —")
            continue
        print(
            f"{mc:5.2f} {result['n']:5d} {fmt(result['b']):>6} {fmt(result['se']):>6} "
            f"{fmt(result['mean']):>6} {fmt(result['max'], 1):>5} {fmt(result['range'], 1):>6}"
        )

    print()
    print("=== other native types (never mixed) ===")
    for magnitude_type, magnitudes in sorted(by_type.items(), key=lambda item: -len(item[1])):
        print(
            f"\n{magnitude_type}: n={len(magnitudes)} "
            f"min={min(magnitudes):.1f} max={max(magnitudes):.1f}"
        )
        for mc in (3.0, 3.5, 4.0, 4.5, 5.0, 5.5):
            result = aki_b_value(magnitudes, mc)
            if result is None or result["n"] < 50 or result["b"] is None:
                continue
            print(
                f"  Mc={mc:.1f} n={result['n']:5d} b={result['b']:.3f} "
                f"se={result['se']:.3f} range={result['range']:.1f} max={result['max']:.1f}"
            )

    print()
    print("=== mb counts at high thresholds (saturation check) ===")
    for threshold in (5.5, 6.0, 6.5, 7.0, 7.5, 8.0):
        print(f"  mb>={threshold:.1f}: {sum(1 for magnitude in mb if magnitude >= threshold)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
