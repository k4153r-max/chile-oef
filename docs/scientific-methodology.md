# Scientific methodology

## Scope

CHILE-OEF forecasts earthquake occurrence as a conditional stochastic process.
It does not forecast a deterministic next earthquake and it does not estimate
risk, which would additionally require exposure and vulnerability.

For issue time `t`, horizon `h`, spatial/depth/tectonic cell `c`, and magnitude
threshold `m`, the primary binary quantity is

\[
P\{N_{c,\ge m}(t,t+h) \ge 1 \mid \mathcal H_t\}.
\]

The system also forecasts the expected count and, where supported, the full
predictive count distribution. Every model input must satisfy
`available_at <= issued_at`; every evaluated target must satisfy
`issued_at < event_time <= valid_until`.

## Scientific progression

1. Empirical base-rate and homogeneous Poisson.
2. Spatially inhomogeneous Poisson and adaptive kernel seismicity.
3. Magnitude completeness and Gutenberg-Richter magnitude distribution.
4. Modified Omori/Reasenberg-Jones sequence forecasts.
5. Temporal, then spatiotemporal, ETAS.
6. IAS as a non-probabilistic activity-anomaly percentile.
7. Machine-learning challengers fitted to incremental information beyond ETAS.
8. GNSS and physics-based challengers only after the statistical core passes
   prospective tests.

No later stage is promoted merely because it is more complex.

## Non-negotiable invariants

- Forecasts are immutable.
- Catalog revisions are append-only.
- Native source observations are never destroyed by canonicalization.
- Magnitude type and conversion lineage are retained.
- Mc is spatially, temporally, and source dependent.
- A forecast below the applicable Mc is `not_estimable`.
- Uncertainty method and coverage level are explicit.
- Scheduled and event-triggered forecasts are distinguishable.
- Research outputs cannot be published by the operational API automatically.

## Uncertainty

Forecast products distinguish:

- aleatory variability of the point process;
- parameter uncertainty;
- catalog/location/magnitude uncertainty;
- model uncertainty.

Intervals for future counts are called predictive intervals. Confidence or
credible intervals are reserved for parameters or estimands under the stated
frequentist or Bayesian procedure.

## Primary references

The versioned bibliography is in `references/bibliography.bib`. The methodological
foundation is Jordan et al. (2011), Ogata (1988, 1998), Utsu et al. (1995),
Mizrahi et al. (2024), and the CSEP/pyCSEP framework.

