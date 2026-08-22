# Forecast improvement review and v2 research slice

Date: 2026-08-22

## Conclusion

The defensible next model is not an opaque earthquake predictor. It is a
registered ETAS challenger that preserves the current total background rate,
redistributes that rate using an independently estimated adaptive spatial
background, represents finite-horizon branching variability with synthetic
catalogs, and must beat the current champion in paired walk-forward evaluation.
It remains experimental until genuine prospective evidence accumulates.

## International systems and lessons adopted

| Program or evidence | Operational/scientific lesson | CHILE-OEF decision |
|---|---|---|
| ICEF/OEF guidelines, Jordan et al. (2011) | Publish timely probabilities, qualify models retrospectively, then test continuously and prospectively against alternatives. | Immutable forecast lineage, freshness state, challenger/champion gate; no deterministic prediction claim. |
| OEF Italy (ETAS, ETES and STEP ensemble) | Daily and event-triggered updates; model diversity is useful only after each component is tested. | Scheduled issuance is idempotent; retain STEP/Reasenberg-Jones and ensemble weighting as later registered challengers. |
| USGS Operational Aftershock Forecasting | Reasenberg-Jones and ETAS, generic/sequence-specific/Bayesian parameters, multiple horizons and regular updates. | ETAS remains the core; parameter posterior propagation is the highest-priority uncertainty gap. |
| Helmstetter-Kagan-Jackson adaptive smoothing | Adaptive kernels provide a strong spatial seismicity reference and must be tuned out of sample. | Use the existing adaptive background as a plug-in challenger, never as an automatic replacement. |
| UCERF3-ETAS | Synthetic catalog ensembles express cascading future triggering and answer threshold questions. | Simulate background immigrants and all finite-horizon descendant generations; expose count quantiles and `P(N>=1)`. |
| CSEP/pyCSEP | N/L/S/M consistency, comparative tests, fixed registrations and prospective experiments are the evaluation standard. | Keep N/L/S/M, likelihood and calibration metrics; require a paired time-block comparison with the actual champion. |
| Recent CSEP power studies | A passed consistency test is not proof of superiority; spatial tests can have very low power with sparse targets. | Promotion requires minimum fold/event support and returns `insufficient_evidence` when S/M support is sparse. |
| Bayesian ETAS literature | Point-estimate parameters make predictive uncertainty too narrow. | Current simulation is explicitly aleatory-only; posterior/bootstrap parameter ensembles remain mandatory before calibrated uncertainty claims. |

## Implemented research slice

### Adaptive spatial background challenger

`generate_forecast_cells` accepts a complete non-negative map of background
cell weights. It normalizes them and redistributes the fitted ETAS `mu` without
changing its region-wide expected background count. Missing cells, non-finite
weights, negative values or zero total mass fail closed. Forecast and evaluation
runs cite the exact `background_rate_run_id`.

This is a plug-in hybrid: the ETAS fit still estimated a homogeneous scalar
background. The spatial surface is not jointly estimated with the triggering
kernel. Therefore it is a challenger (`etas_gr_adaptive_background_grid_forecast_v2`),
not a theoretically final model.

### Finite-horizon predictive catalogs

The simulator samples Gutenberg-Richter magnitudes, conditional Omori times,
background events, descendants of the observed history and secondary future
triggering. It reports mean, median, 2.5/5/95/97.5 percentiles and probability
of at least one event per estimable magnitude bin. A catalog explosion fails
rather than being silently truncated.

The catalog ensemble currently integrates over the modeled plane and represents
aleatory branching uncertainty at fixed parameters. It does not yet assign
simulated events to cells, vary ETAS/GR/background parameters, or propagate
catalog location/magnitude uncertainty.

### Stability diagnostics

Every forecast reports whether `alpha < b ln(10)`, whether `p > 1`, the
finite-horizon magnitude-averaged direct offspring expectation, and (only when
defined) the lifetime branching estimate. A `p <= 1` fit is labeled
`finite_horizon_only_p_not_above_one`; finite forecasts remain computable, but
no finite lifetime branching interpretation is claimed.

### Operational issuance and promotion

`issue-operational-forecast` serializes an issue slot with a PostgreSQL advisory
lock, reuses an existing scheduled run, and selects the latest compatible
converged ETAS/GR/background lineage. `/v1/forecasts/status` distinguishes
missing, future, expired, stale and fresh products.

`run-walk-forward-evaluation --background-rate-run-id ...` evaluates the
challenger with exact lineage. `assess-model-promotion` requires candidate and
champion runs with identical protocols and folds, then block-bootstraps their
paired point-process log-likelihood difference per observed event. Promotion
also requires calibration and N/L/S/M consistency thresholds. Missing evidence
returns `insufficient_evidence`; a sufficiently tested but inferior candidate
returns `retain_champion`.

## Next research priorities

1. Generate parameter ensembles (parametric bootstrap first; Bayesian ETAS as
   the stronger challenger) and mix them with catalog simulations.
2. Simulate full space-time-magnitude catalogs, including boundary correction,
   to produce cell-level predictive intervals and catalog-based CSEP tests.
3. Tune adaptive-background bandwidth and all challenger choices exclusively
   inside nested historical folds; never on the prospective evaluation window.
4. Register Reasenberg-Jones/STEP and a stationary adaptive-smoothed Poisson
   baseline; consider ensembles only after individual prospective evidence.
5. Automate event-triggered issuance with catalog-latency and source-freshness
   service-level objectives.
6. Accumulate real prospective Chilean forecasts. No retrospective code can
   substitute for elapsed, sealed prospective outcomes.

## Primary references

- Jordan et al. (2011), Operational Earthquake Forecasting guidelines:
  <https://doi.org/10.4401/ag-5350>
- Marzocchi et al. (2023), ten-year validation of OEF Italy:
  <https://doi.org/10.1093/gji/ggad256>
- USGS Operational Aftershock Forecasting scientific overview:
  <https://earthquake.usgs.gov/data/oaf/overview.php>
- Helmstetter, Kagan and Jackson adaptive-smoothed seismicity model:
  <https://doi.org/10.1785/0120060061>
- Milner et al. (2020), operational UCERF3-ETAS during Ridgecrest:
  <https://doi.org/10.1785/0220190294>
- pyCSEP evaluation concepts and registered tests:
  <https://docs.cseptesting.org/concepts/evaluations.html>
- Khawaja et al. (2023), statistical power of spatial forecast tests:
  <https://doi.org/10.1093/gji/ggad030>
- Nandan et al., Bayesian estimation of ETAS and parameter uncertainty:
  <https://arxiv.org/abs/2109.05894>
