# Why the first real-catalog b-value is 2.13

Status: documented finding, 2026-08-16. Not a code defect. Not a
recalibration. The live Gutenberg-Richter row stays `b=2.13` until a new
estimate is issued on a magnitude type that can actually resolve large
events.

## What was checked

The production fit used USGS ComCat, Chile box (−60/−15°S, −82/−62°E),
window 2005-01-01..2015-01-01, magnitude type `mb`, Mc from Entire
Magnitude Range = 4.97, then Aki (1965) MLE with the 0.1-bin Utsu
correction already in `estimate_b_value`.

`scripts/diagnose_b_value.py` re-pulled that exact FDSN query
(16,103 events; 7,493 of them `mb`) and recovered **b = 2.131 ± 0.098
over 483 events**, matching the persisted production row to three
decimals. The binning correction is not the cause.

## What the number actually is

`mb` in this sample saturates at 6.2. There are **zero** `mb ≥ 6.5`
events. The 27F Maule mainshock (Mw 8.8) is stored as `mww`, not `mb`.
Above Mc = 4.97 the usable range is 1.2 magnitude units, and 200 of the
483 events sit in the first 0.1 bin (5.0).

Aki's estimator then sees a mean magnitude of 5.15 against an effective
origin of 4.95, so `b = log10(e) / 0.204 ≈ 2.13`. That is the correct
MLE of a sample pressed against the reporting ceiling of `mb`, not a
regional tectonic slope.

The same estimator on the same `mb` events at a lower Mc is ordinary:

| Mc | n | b | range |
|---:|--:|--:|------:|
| 4.0 | 6830 | 0.84 | 2.2 |
| 4.5 | 3344 | 1.57 | 1.7 |
| 4.97 (production) | 483 | 2.13 | 1.2 |

`md` and `ml` show the same climb as Mc approaches their own ceilings
(4.8 and 5.1). Moment-magnitude types in the same window do not:

| type | Mc | n | b | max |
|------|---:|--:|--:|----:|
| mwc | 5.0 | 505 | 1.12 | 7.7 |
| mww | 5.0 | 154 | 0.55 | 8.8 |
| mwb | 5.0 | 123 | 0.53 | 7.8 |

`mww`/`mwb` at Mc = 5 are incomplete at the small end (they exist because
the event was large), so those b-values are biased **low**. They are
shown as contrast, not as a replacement number.

## Why this matters for the live forecast

`ForecastService` allocates ETAS rates across magnitude bins with this
b-value. Under Gutenberg-Richter,

`P(M ≥ 7 | M ≥ 5) = 10^(-b · 2)`

- b = 2.13 → ~5.5×10⁻⁵
- b = 1.0 → 10⁻²

The live 7-day forecast therefore **understates large-event bins**
relative to any moment-magnitude description of Chile. The map is still
an uncalibrated relative-activity picture; it is not a megathrust
probability product. That limitation is now also stated on
`etemen.cl/chile-oef/`.

## What is not allowed as a "fix"

- Do not overwrite the persisted row.
- Do not silently substitute `mww` into the `mb` Mc window.
- Do not invent a magnitude conversion. `config/magnitude-policy.yaml`
  requires a versioned relation before any overwrite.
- Do not treat USGS `updated` as historical `available_at`.

## Next honest slice

Done 2026-08-17: new `mwc` EMR + Aki + ETAS + P7D forecast
(`c29cd2b3-73de-4c60-92e7-afdd42c2da6f`), b=1.12, Mc=4.999. The `mb`
row was not overwritten. CSN remains `enabled: false` until the license
review in `docs/data-sources.md`.
