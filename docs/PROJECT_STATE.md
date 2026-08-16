# CHILE-OEF continuity and handoff log

Last updated: 2026-08-16, America/Santiago

This file is the durable context for a new Claude/Codex session. Read it before
editing. Keep it current. The chat history is not required to resume the project.

## Mission and scientific boundary

CHILE-OEF is an experimental, auditable Operational Earthquake Forecasting (OEF)
research platform for Chile. It estimates occurrence rates, expected counts and
conditional probabilities over declared spatial cells, magnitude bins and future
time windows. It does not predict an exact earthquake, provide early warning, or
replace CSN/SENAPRED.

The research question is whether observable seismic, tectonic and later geodetic
information improves prospective probabilistic forecasts over accepted baselines.
A null result, including “ML does not improve ETAS”, is valid.

Non-negotiable invariants:

- `forecast_time < event_time`, without exceptions;
- selection for replay/backtests uses `available_at`, not only earthquake origin
  time or the latest catalog revision;
- raw observations and every source revision are retained;
- forecasts are append-only; recalculation creates a new forecast;
- IAS measures anomaly, not seismic hazard or probability of a large earthquake;
- no random train/test split for temporal forecasts;
- no ML before Mc, Gutenberg–Richter, background, Omori, ETAS and backtesting;
- uncertainty, provenance, calibration status and failure modes travel with every
  scientific result.

Permanent public disclaimer:

> CHILE-OEF es una plataforma experimental de investigación que analiza patrones
> estadísticos de actividad sísmica. No predice terremotos de forma determinista y
> no reemplaza información oficial del Centro Sismológico Nacional, SENAPRED ni
> otras autoridades.

## Repository and environment

Workspace:
`/home/k4153r/Documents/Codex/2026-08-16-quiero-que-act-es-como-un`

Git was initialized on 2026-08-16. Initial commit `eea1333` captured Phase 0-2
as they stood at that point (no prior history exists to preserve — the
directory had never been under version control). The Phase 3 slice below was
committed separately on top of it.

Stack: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic,
PostgreSQL/PostGIS, NumPy/Pandas/SciPy/GeoPandas/Shapely/ObsPy, later pyCSEP and
scikit-learn/XGBoost. Dependency lock is `uv.lock`; package definition is
`pyproject.toml`. Local PostGIS is defined by `compose.yaml`.

Useful commands:

```bash
uv sync --extra dev --frozen
docker compose up -d db
uv run alembic upgrade head
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run alembic check
```

Integration tests require `CHILE_OEF_TEST_DATABASE_URL` and refuse to modify a
database whose name does not end in `_test`.

## Milestone status

### Phase 0 — scientific and data contracts: implemented

Implemented design documents cover methodology, data sources, limitations,
forecast contracts, data governance, completeness, backtesting, IAS,
communication and ADRs. JSON contracts exist for event revisions, source events,
dataset manifests, forecasts and model cards.

Important architectural decisions:

- modular monolith, not premature microservices/Kafka/Kubernetes;
- PostgreSQL/PostGIS is the system of record;
- raw inputs are content-addressed and immutable;
- source catalogs are bitemporal through `event_time`, `received_at`,
  `available_at`, source revision time and stored revisions;
- deterministic CSEP-compatible regular grid first; adaptive grids are research
  experiments and cannot silently replace the evaluation grid;
- research models cannot enter operational output without prospective evidence.

### Phase 1 — catalog foundation: implemented and previously validated

Implemented:

- USGS GeoJSON feed adapter and bounded USGS FDSN Event adapter;
- CSN daily HTML parser, kept disabled/research-only because no stable documented
  CSN event API was found; do not invent one;
- raw artifact archive with hashes and source URLs;
- ingestion runs/artifact linkage and failure audit;
- normalized source events and immutable revisions;
- quality flags;
- probabilistic duplicate candidates plus canonical events without deleting
  original observations;
- immutable content-addressed dataset manifests selected by `available_at`;
- historical replay clock/engine;
- read-only FastAPI catalog, provenance, source-status and dataset endpoints;
- Alembic migrations `0001` and `0002`;
- unit, contract and PostGIS integration tests.

The original Phase 1 gate passed 24 tests and a real bounded USGS ingestion stored
two M4.2 events. Phase 1 is also covered by the current 39-test full gate.

### Phase 2 — tectonic engine: implemented and validated

Implemented and validated:

- pinned tectonic asset registry: `config/tectonic-assets.yaml`;
- classifier parameters: `config/tectonic-classifier.yaml`;
- typed registry and checksum/byte-length verified asset acquisition;
- Slab2 XYZ parsing, longitude conversion from 0–360 to −180–180, positive-down
  depth conversion, Chile-area subset loading and bilinear lookup;
- circular interpolation for Slab2 strike (prevents 359° and 1° averaging to 180°);
- CHAF shapefile parser and surface-trace distance in PostGIS geography;
- deterministic 0.1° grid builder with Decimal arithmetic and spherical cell area;
- versioned `tectonic_releases`, `tectonic_assets`, `slab_nodes`, `fault_traces`,
  `spatial_grids`, `seismic_cells`, and append-only
  `event_tectonic_classifications` models;
- Alembic migrations `0003` and `0004`;
- uncalibrated rule baseline that propagates event-depth and Slab2 uncertainty;
- CLI: `init-grid`, `ingest-slab2`, `ingest-chaf`, `classify-tectonics`;
- API: `/v1/grids`, `/v1/cells`, `/v1/tectonics/releases`,
  `/v1/tectonics/slab/sample`, and revision classifications;
- retry-safe HTTP acquisition plus hash-verified audited local import for static
  assets;
- JSON contracts, unit, data and end-to-end PostGIS integration tests.

Final gate on 2026-08-16: **39 tests passed**, Ruff passed, formatting passed,
`alembic upgrade head` reached `0004`, and `alembic check` reported no new upgrade
operations.

Real-data smoke validation:

- grid `chile_regular_0_1_v1`: 90,000 cells, definition SHA-256
  `456fbcb594b545175b31001934dffc843947f00c5213cd4e554c0076765491fc`;
- CHAF: 958 traces loaded from the pinned PANGAEA ZIP;
- Slab2: five pinned assets loaded over HTTP and 115,124 finite nodes retained in
  the Chile/circum-Chile bounds;
- two existing real USGS event revisions classified; both were `intraslab` under
  the uncalibrated v1 rule, with maximum masses 0.8053–0.8801. This is a pipeline
  smoke test, not classifier validation or predictive evidence;
- observed peak Slab2 loader memory was roughly 318 MB and total wall time roughly
  7.5 minutes, dominated by intermittent ScienceBase response delays.

Tectonic scientific decision:

- The Phase 2 output is `calibration_status=uncalibrated_rule_baseline`.
- It partitions Gaussian uncertainty mass in event-depth-minus-slab-depth into
  interface, intraslab, shallow above-slab crustal and unknown categories.
- `outer_rise` and `volcanic` are explicitly zero/disabled in v1 because Slab2
  residual alone cannot defend those labels.
- CHAF nearest-trace distance is diagnostic only and does not alter category
  probability; arbitrary weights are forbidden.
- `signed_normal_distance_km = vertical_residual * cos(dip)` is a local planar
  projection, not a true closest distance to a 3-D triangulated slab surface.
- A hard label is emitted only above the configured 0.60 mass threshold; otherwise
  it is `unknown`.
- These uncertainty masses must not be described as empirically calibrated class
  probabilities. Promotion requires an independently labeled Chilean test catalog,
  reliability assessment and temporal/spatial holdout.

### Phase 3 — magnitude of completeness (Mc): first estimator implemented and validated

Scope delivered on 2026-08-16, deliberately kept to one estimator rather than
implementing Maximum Curvature, Goodness-of-Fit and Entire-Magnitude-Range
bootstrap together (see docs/completeness.md's own gate discipline):

- `src/chile_oef/seismicity/catalog_selection.py`: availability-safe magnitude
  sample selection. Reuses `db/repositories/events.py::list_events`, whose
  preferred-revision query already enforces `available_at <= as_of`; adds only
  the single-magnitude-type restriction Mc requires (`select_single_magnitude_type`).
- `src/chile_oef/seismicity/completeness.py`: `support_state` implementing the
  exact reporting bands from docs/completeness.md (>=200 supported, 100-199
  high_uncertainty, 50-99 research_only, <50 not_estimable — not_estimable
  means no Mc value is computed at all, not just a low-confidence one) and
  `estimate_mc_maximum_curvature`, the Wiemer & Wyss (2000) maximum-curvature
  estimator with the standard +0.2 correction. Per docs/completeness.md this
  method is registered as **diagnostic only**; the primary estimator (Entire
  Magnitude Range with bootstrap uncertainty) is not implemented yet.
- `src/chile_oef/db/models/seismicity.py::CompletenessEstimate` +
  Alembic migration `0005`: append-only persistence (no update/delete path,
  matching the forecast-immutability invariant); stores time window, spatial
  bounding box, magnitude type, event count, uncertainty/support state,
  method/version, role, and `catalog_as_of`.
- `src/chile_oef/seismicity/service.py::CompletenessEstimationService` and CLI
  `estimate-completeness` wire selection -> estimation -> persistence.
- Tests: `tests/unit/test_completeness.py` (support-band boundaries, a fixed
  literal-catalog regression fixture pinning the exact histogram peak and
  correction, exact-correction-application check for arbitrary policy values,
  and a seeded synthetic Gutenberg-Richter-with-logistic-rolloff recovery
  check used only as a loose sanity bound, not a precision claim);
  `tests/unit/test_catalog_selection.py` (pure filtering, timezone/window
  validation); `tests/integration/test_completeness_pipeline.py` (real
  ingestion + Postgres: proves a revision whose `available_at` is after
  `as_of` is excluded even though its `event_time` falls inside the window,
  and that a 200-event supported-band run persists correctly).

Final gate on 2026-08-16: **58 tests passed** (39 prior + 19 new), Ruff and
`ruff format --check` passed, `alembic upgrade head` reached `0005`, and
`alembic check` reported no new upgrade operations. CLI smoke-tested against
the real dev database (`estimate-completeness` over an empty window returned
`event_count=0 support_state=not_estimable`, then the resulting row was
deleted since it carried no real events).

Explicitly not done in this slice: Entire Magnitude Range with bootstrap
uncertainty (the actual primary estimator), spatial adaptive-neighborhood Mc
(this slice only supports a fixed bounding box or no spatial filter at all),
tectonic-class-conditioned Mc, and any API endpoint (only CLI exists so far).
None of these should be assumed implemented just because this section exists.

### Phase 3 continued — Goodness-of-Fit cross-check implemented and validated

Added on 2026-08-16, same session as the Maximum Curvature slice above:

- `estimate_mc_goodness_of_fit` in `src/chile_oef/seismicity/completeness.py`:
  Wiemer & Wyss (2000) goodness-of-fit method. For each candidate bin,
  ascending, fits a Gutenberg-Richter line by Aki (1965) MLE using only
  events at or above that candidate, then measures what percentage of the
  observed cumulative distribution (candidate to the largest observed bin,
  including empty intermediate bins) that line reproduces. Mc is the smallest
  candidate reaching 95% fit quality; if none does, the smallest reaching
  90%; if neither is reached, `mc_value` is `None` rather than silently
  returning whichever candidate scored highest.
- A real failure mode was caught and fixed before landing: with only a
  minimum-event-count guard, sparse high-magnitude tail bins could trivially
  "pass" the fit threshold on pure noise (verified with 500 uniform-random
  magnitudes, which spuriously reached 95% at the top bin). Fixed by also
  requiring a minimum span of bins (10, configurable
  `goodness_of_fit_minimum_bins_above_candidate`) between the candidate and
  the largest observed bin, not just a minimum event count. Re-verified: the
  same noise catalog now correctly returns `mc_value=None`.
- `CompletenessEstimationService.estimate_goodness_of_fit` and
  `chile-oef estimate-completeness --method goodness_of_fit` wire it through
  the same availability-safe selection and append-only persistence as
  Maximum Curvature (same `completeness_estimates` table; no new migration
  needed — GFT-specific fields go in `diagnostics_json`).
- Tests added: a deterministic (no RNG) exact-Gutenberg-Richter regression
  fixture that recovers `mc_value=3.0` at 95% confidence with ~99.6% fit
  quality; the pure-noise refusal case above; the not-estimable case; and an
  integration test proving the full ingest -> select -> estimate -> persist
  path for this second estimator.

Final gate on 2026-08-16 (Phase 3, MaxC + GFT): **62 tests passed** (58 prior
+ 4 new), Ruff, `ruff format --check`, and `alembic check` all passed.

### Phase 3 continued — Entire Magnitude Range (primary estimator) implemented and validated

Added on 2026-08-16, same session. This is the estimator docs/completeness.md
actually registers as primary; Maximum Curvature and Goodness-of-Fit stay
`role=diagnostic` cross-checks and were not changed.

- Added `numpy` and `scipy` as real dependencies (first numerical
  dependencies in the project; previously deferred as "later" in this file).
  `uv.lock` updated accordingly.
- `estimate_mc_entire_magnitude_range` in `completeness.py`: Ogata & Katsura
  (1993) method. Jointly fits, by maximum likelihood, `mu` (the 50%-detection
  magnitude, reported as `mc_value`), `sigma` (detection rolloff width), and
  the Gutenberg-Richter `b`-value, using a discretized Poisson-process
  likelihood (Gutenberg-Richter rate x normal-CDF detection function, binned
  at `bin_width_magnitude`) optimized with `scipy.optimize.minimize`
  (L-BFGS-B, bounded). Initial guess reuses the Maximum Curvature peak for
  `mu` and an Aki-style estimate for `beta`.
- Uncertainty: nonparametric bootstrap (`numpy.random.default_rng`, seeded
  and configurable; default 200 resamples, refit from the point estimate
  each time for speed), reporting a percentile confidence interval on
  `mc_value` at the configured level (default 95%).
- Point estimation that fails to converge, or a catalog with too few events,
  returns `mc_value=None` rather than a value the optimizer did not actually
  converge on -- same refuse-rather-than-guess discipline as Goodness-of-Fit.
- Verified against the exact generative model it assumes (Gutenberg-Richter
  thinned by a normal-CDF detection function, seeded rejection sampling):
  with 3000 synthetic events at true `mu=3.0, sigma=0.1, b=1.0`, recovered
  `mu=2.997, sigma=0.104, b=1.001` with a 95% bootstrap interval
  `(2.984, 3.018)` correctly bracketing the true value. This is a
  correctly-specified-model check (unlike MaxC/GFT's cross-check role, EMR
  is expected to be numerically precise here, not just in the right
  neighborhood) -- committed test tolerances are loosened only to absorb
  Monte Carlo sampling noise and a reduced bootstrap count for test speed.
- `CompletenessEstimationService.estimate_entire_magnitude_range` and
  `chile-oef estimate-completeness --method entire_magnitude_range` wire it
  through the same availability-safe selection and `completeness_estimates`
  table (sigma, b-value, and the confidence interval go in
  `diagnostics_json`; no new migration).
- Tests added: not-estimable case; synthetic-recovery precision check;
  role/calibration_status assertions (`role="primary"`,
  `calibration_status="uncalibrated_primary_estimator"`); an integration test
  proving the full ingest -> select -> fit -> bootstrap -> persist path.

Final gate on 2026-08-16 (Phase 3 total, all three estimators): **65 tests
passed** (62 prior + 3 new), Ruff, `ruff format --check`, and `alembic check`
all passed. CLI smoke-tested against the real dev database with
`--method entire_magnitude_range`; the resulting empty-catalog row was
deleted afterward since it carried no real events.

### Phase 3 continued — Gutenberg-Richter b-value implemented and validated

Added on 2026-08-16, same session. Resolves the design question this file
previously left open (whether to reuse EMR's internal b-value byproduct or
re-estimate independently): re-estimates independently.

- `src/chile_oef/seismicity/gutenberg_richter.py::estimate_b_value`: classical
  Aki (1965) maximum-likelihood b, restricted to events at or above a
  *declared* Mc that the caller must supply -- this function does not derive
  Mc itself. Deliberately does not reuse the `b_value` Entire Magnitude
  Range fits internally, because that value is a byproduct of a different
  joint MLE (over the full magnitude range including the sub-threshold
  detection rolloff, fit to find Mc), not the classical supra-threshold
  estimator docs/scientific-methodology.md lists as its own distinct
  progression step. Uncertainty uses the Shi & Bolt (1982) standard error
  (uses observed sample variance rather than assuming a perfect exponential
  the way Aki's original `b/sqrt(N)` does).
- `src/chile_oef/db/models/seismicity.py::GutenbergRichterEstimate` + Alembic
  migration `0006`: append-only, with a **mandatory foreign key** to the
  specific `CompletenessEstimate` row whose `mc_value` was used --
  implementing docs/completeness.md's "Every downstream statistic stores the
  Mc result it used" literally, not just as a copied float.
- `GutenbergRichterEstimationService.estimate_for_completeness_estimate`
  takes only a `completeness_estimate_id`; it derives the time window,
  magnitude type, and spatial filters from that row rather than accepting
  them as separate arguments, and raises `ValueError` if the row has no
  `mc_value` (e.g. its own support_state was `not_estimable`). This makes it
  structurally impossible to fit a b-value against a Mc from a mismatched
  window or region, rather than relying on a runtime consistency check.
- CLI: `chile-oef estimate-gutenberg-richter --completeness-estimate-id <uuid>`.
- Verified against an exact synthetic Gutenberg-Richter catalog (no RNG):
  1000 events at true `b=1.0` recovered `b=0.9965`, with the fitted a-value
  reproducing the observed count at Mc to within 1e-6 relative error by
  construction of the MLE anchoring. Also verified b=0.8 and b=1.3 synthetic
  catalogs are correctly ordered and each recovered within 0.02 of their
  true value.

Final gate on 2026-08-16 (Phase 3 total, all three Mc estimators + GR):
**71 tests passed** (65 prior + 6 new), Ruff, `ruff format --check`, and
`alembic check` all passed.

### Phase 3 continued — nearest-neighbor declustering implemented and validated

Added on 2026-08-16, same session. First model of this project that chains
three prior results together end to end: it takes a
`gutenberg_richter_estimate_id` and derives its Mc, b-value, window,
magnitude type, and spatial filters from that row (which itself derives its
window/Mc from a `completeness_estimate_id`), rather than accepting any of
those as independent arguments.

- `src/chile_oef/seismicity/declustering.py::decluster`: nearest-neighbor
  method (Baiesi & Paczuski 2004; Zaliapin & Ben-Zion 2013). For each event,
  ordered by time, computes eta = t_ij * r_ij^df * 10^(-b*m_i) against every
  earlier event (haversine distance, vectorized per event with numpy) and
  keeps the minimum as that event's nearest-neighbor distance and inferred
  parent. `log10(eta)` is bimodal (triggered vs. background pairs); the
  threshold separating them is fit with a from-scratch univariate
  two-component Gaussian-mixture EM (no new dependency: pure numpy +
  `scipy.optimize.brentq` for the crossover point, not scikit-learn, which
  stays deferred to Phase 7 as originally planned). The fractal dimension
  (`df=1.6`, the literature default for southern California) is a declared,
  uncalibrated default -- no Chile-specific value has been fit.
  Below the minimum-sample threshold, or if the EM/threshold cannot be fit,
  events are left explicitly unclassified (`is_background=None`), not
  defaulted either way. The very first event chronologically in a window is
  trivially background (no earlier event to be triggered by, within that
  window).
- `db/models/seismicity.py::SeismicityDeclusteringRun` (append-only,
  mandatory FK to the `GutenbergRichterEstimate` it used) and
  `EventDeclusteringClassification` (one append-only row per event per run,
  FK to `EventRevision`, nullable FK to its inferred parent
  `EventRevision`) + Alembic migration `0007`.
- `catalog_selection.py::fetch_declustering_catalog`: like
  `fetch_magnitude_catalog` but also returns coordinates and filters to a
  minimum magnitude (the declared Mc) -- below Mc the catalog is not
  complete enough for the space-time-magnitude metric to be meaningful.
- `DeclusteringService.decluster_for_gutenberg_richter_estimate` and
  `chile-oef decluster --gutenberg-richter-estimate-id <uuid>`.
- Verified on a synthetic catalog with known background events (uniform in
  space/time) and known aftershock sequences (tightly clustered near
  mainshocks): recovered 296/300 background events and 200/200 triggered
  events correctly in one seeded draw; committed unit tests use looser
  bounds (>85%/>90%) across the population, not that single draw's exact
  numbers. A second, real-ingestion-backed integration test (through
  Postgres, not just the pure function) recovers similar separation on
  ingested/queried data.
- Known correctness edge cases handled: same-timestamp and same-location
  event pairs (floored at 1 second / 1 meter to avoid `log(0)`); empty
  catalogs; catalogs below the minimum sample size for the threshold fit.
- Known limitation, not yet addressed: nearest-neighbor computation is
  O(n^2) per window (vectorized with numpy, not a spatial index) -- fine at
  the current catalog scale, a documented later optimization at larger
  scale, same pattern as the Slab2 loader's known memory-scaling note.

Final gate on 2026-08-16 (Phase 3 total, four estimators + declustering):
**78 tests passed** (72 prior + 6 new), Ruff, `ruff format --check`, and
`alembic check` all passed. Migration `0007` applied cleanly against the
real dev database with `alembic check` reporting no drift.

### Phase 3 continued — smoothed adaptive-kernel background rate implemented and validated

Added on 2026-08-16, same session. Second model to chain three prior results
together, and the first to touch Phase 2 infrastructure: it takes a
`declustering_run_id` and a `grid_id` and evaluates the background subset's
smoothed rate on that specific Phase 2 grid (`spatial_grids`/`seismic_cells`)
-- the grid built for tectonic classification is now reused for seismicity,
not duplicated.

- `src/chile_oef/seismicity/background_rate.py::estimate_background_rate`:
  Helmstetter, Kagan & Jackson (2007) adaptive Gaussian kernel. Each
  background event's bandwidth is its haversine distance to its k-th
  nearest *other* background event (`k=5`, a declared uncalibrated default,
  floored at 1 km to avoid near-duplicate locations producing a spuriously
  sharp kernel); summing all kernels at a grid cell's center gives a spatial
  density that, divided by the observation duration in years and multiplied
  by the cell's area (already stored from Phase 2's grid builder), gives an
  expected annual event count for that cell.
- Verified via the estimator's own mass-conservation identity: summed over a
  grid padded well beyond the kernel bandwidths,
  `sum(density_per_km2 * cell_area_km2)` recovers the background event count
  to within 1% (199.999 vs. 200 in one check), and the equivalent
  unpadded-grid sum recovers noticeably less -- both the correct-math case
  and the documented finite-domain edge-effect are pinned as tests, not just
  the happy path.
- `db/models/seismicity.py::SeismicityBackgroundRateRun` (append-only, FKs
  to both `SeismicityDeclusteringRun` and `SpatialGrid`) and
  `SeismicCellBackgroundRate` (one append-only row per cell per run, FK to
  `SeismicCell`) + Alembic migration `0008`.
- `BackgroundRateService.estimate_for_declustering_run` and
  `chile-oef estimate-background-rate --declustering-run-id <uuid> --grid-id <id>`.
- A real-ingestion-backed integration test runs the full four-step chain
  (ingest -> Mc -> b -> decluster -> background rate) against a real Phase 2
  grid created in the same test via `GridService`, confirming both the
  provenance FKs and the mass-conservation identity hold on queried
  (not just synthetically constructed) data.
- Known limitation, not yet addressed: bandwidth computation is O(n^2) in
  the background event count (vectorized per event, not a spatial index),
  and rate evaluation is O(n_events x n_cells) -- fine at current catalog
  scale; documented the same way as declustering's and Slab2's known
  scaling notes, not treated as a correctness blocker.

Final gate on 2026-08-16 (Phase 3 total, five estimators + declustering +
background rate): **85 tests passed** (78 prior + 7 new), Ruff,
`ruff format --check`, and `alembic check` all passed. Migration `0008`
applied cleanly against the real dev database.

### Phase 3 continued — Modified Omori-Utsu aftershock sequences implemented and validated

Added on 2026-08-16, same session. Completes item 6 of Exact next work (all
of: three Mc estimators, Gutenberg-Richter, declustering, smoothed
background rate, Modified Omori now exist).

- `src/chile_oef/seismicity/modified_omori.py::estimate_modified_omori`:
  Ogata (1983) maximum-likelihood fit of `n(t) = K/(t+c)^p` to one
  aftershock sequence's arrival times. `K` is profiled out analytically
  given `(c, p)`, leaving a 2-parameter numerical optimization. The
  observation duration `T` used in the likelihood integral is an explicit
  required argument (time from the root/triggering event to the end of the
  analysis window) -- deliberately not `max(event_times)`, which would
  truncation-bias the fit toward whatever happened to be observed rather
  than the true window.
- A real convergence failure was hit and fixed during integration testing,
  not invented for the changelog: on a real declustering run's largest
  family (390 events), `scipy.optimize.minimize` with `L-BFGS-B` returned
  `ABNORMAL_TERMINATION_IN_LNSRCH`. Fixed with an explicit Nelder-Mead
  fallback (gradient-free, slower, more robust to this likelihood surface's
  curvature) rather than silently lowering tolerances or picking a
  different default method; the diagnostics record which optimizer actually
  produced the result (`optimizer_message`/`lbfgsb_message`) so this isn't
  hidden.
- Family resolution (`service.py::_resolve_family_roots`): for every
  triggered event, walks its `parent_event_revision_id` chain up to the
  nearest background ancestor (handles secondary triggering -- an
  aftershock triggering its own aftershock -- not just immediate parent
  grouping). Events whose chain resolves to `None`/unclassified rather than
  a confirmed background root are excluded rather than guessed into a
  family.
- `db/models/seismicity.py::ModifiedOmoriSequenceEstimate` (append-only, FK
  to `SeismicityDeclusteringRun` and to the family's root `EventRevision`)
  + Alembic migration `0009`.
- `ModifiedOmoriService.estimate_for_declustering_run` fits every family
  with at least one triggered event in a run (families below the minimum
  sample size still get a `not_estimable` row, for the same auditability
  reason every other estimator here persists refusals). CLI:
  `chile-oef fit-modified-omori --declustering-run-id <uuid>`.
- Verified against an independently re-derived (not calling into the module
  under test) inverse-CDF sample from the exact `K/(t+c)^p` process: at
  `K=50, c=0.05, p=1.1`, recovered `p=1.11`, `c=0.041`, `K=44.1` (K is the
  most sample-variance-sensitive of the three, since it compounds errors in
  `c` and `p` through the likelihood integral). A Postgres-backed
  integration test runs the full five-step chain (ingest -> Mc -> b ->
  decluster -> Modified Omori) with a real magnitude-6.0 mainshock and a
  384-event synthetic Omori-decaying sequence; the resolved family recovers
  ~390 events (a magnitude-6.0 mainshock has a large "reach" in the
  nearest-neighbor eta metric, so a handful of unrelated background events
  get pulled in -- an expected declustering characteristic documented in
  the test, not silently hidden by a loose enough tolerance to look exact)
  and `p` within 0.3 of the true value.

Final gate on 2026-08-16 (Phase 3 total, all six pieces of item 6): **91
tests passed** (85 prior + 6 new), Ruff, `ruff format --check`, and
`alembic check` all passed. Migration `0009` applied cleanly against the
real dev database.

### Phase 4 started — temporal ETAS implemented and validated

Added on 2026-08-16, same session. First Phase 4 model
(docs/scientific-methodology.md item 5: "Temporal, then spatiotemporal,
ETAS"). Genuinely harder than everything in Phase 3: a 5-parameter joint
MLE over the *entire* catalog at once (not per-family like Modified Omori),
with an O(n^2) likelihood.

- `src/chile_oef/seismicity/etas.py::estimate_temporal_etas`: Ogata (1988)
  conditional intensity `lambda(t) = mu + sum_{t_j<t} k0*exp(alpha*(m_j-mc))/(t-t_j+c)^p`,
  fit by maximum likelihood (`sum(log(lambda(t_i))) - integral(lambda) dt`
  over the observation window). No hard parent/family assignment is used or
  needed -- every earlier event contributes to every later event's rate,
  unlike declustering's nearest-neighbor parent links.
- Fit with several restarts from different starting points (default: one
  seeded from a crude background-rate-style guess, the rest random within
  bounds; `TemporalEtasService` instead seeds from a declustering run's
  averaged Modified Omori `(K, c, p)` when one is supplied, per this file's
  own earlier guidance) and keeps the best (highest-likelihood) converged
  result. Each restart tries `L-BFGS-B` first, falling back to Nelder-Mead
  on failure (same pattern established for Modified Omori).
- A real, literature-documented ETAS estimation characteristic was
  encountered and is explicitly handled, not hidden: with modest triggered-
  event counts, `k0`/`alpha`/`c` are weakly identified and can converge to
  parameter-bound boundaries (`alpha=0`, `p=3` were both observed during
  development on smaller synthetic catalogs). This is not a bug in the
  implementation -- it is why the restart strategy and the "not just a
  local optimum" framing exist, and why `TemporalEtasEstimate.support_state`
  can legitimately be `"estimable"` with parameters that are only loosely
  constrained; downstream consumers must not treat a converged ETAS fit as
  automatically precise.
- Verified against a from-scratch branching-process (Hawkes) simulation of
  the *exact* model being fit (background immigrants + self-exciting
  offspring generated only within the finite observation window, matching
  the likelihood's own truncation) -- the only reliable way to validate an
  ETAS MLE, per the literature. At `mu=1.0, k0=0.043, alpha=1.0, c=0.1,
  p=1.2` over 300 days (506 events, seed-fixed and fully reproducible),
  recovered `mu=1.20, k0=0.028, alpha=0.81, c=0.072, p=1.238` -- correct
  order of magnitude and sign on every parameter, with `mu` and `p` (the
  best-identified) recovered more precisely than `k0`/`alpha`/`c`
  (expected, and reflected in the committed test's per-parameter
  tolerances, not papered over with one loose blanket tolerance).
- `db/models/seismicity.py::TemporalEtasEstimate` (append-only, mandatory FK
  to `CompletenessEstimate`, optional FK to the `ModifiedOmoriSequenceEstimate`
  that seeded its initial guess when one was used) + Alembic migration
  `0010`. `TemporalEtasService.estimate_for_completeness_estimate` takes a
  `completeness_estimate_id` (required) and `declustering_run_id`
  (optional, seeds the starting point only -- ETAS does not require
  declustering to run). CLI:
  `chile-oef fit-temporal-etas --completeness-estimate-id <uuid> [--declustering-run-id <uuid>]`.
- Known limitation, not yet addressed: the O(n^2) likelihood means fitting
  time grows quadratically with catalog size (500 events with a handful of
  restarts already takes tens of seconds); documented the same way as
  declustering's and the background rate's known O(n^2)/O(n*m) scaling
  notes -- fine at current catalog scale, a real optimization target before
  this is used on a large real catalog.

Final gate on 2026-08-16: **96 tests passed** (91 prior + 5 new), Ruff,
`ruff format --check`, and `alembic check` all passed. Migration `0010`
applied cleanly against the real dev database. Full suite runtime is now
~117 seconds, up from ~80s before this addition, driven almost entirely by
the ETAS synthetic-recovery test's restart cost -- worth watching as more
slices are added, though not yet a problem.

### Phase 4 continued — spatiotemporal ETAS implemented and validated

Added on 2026-08-16, same session. Adds an Ogata (1998) isotropic power-law
spatial triggering kernel to temporal ETAS's Omori-law temporal kernel:

```
lambda(t,x,y) = mu/A + sum_{t_j<t} k0*exp(alpha*(m_j-mc)) / (t-t_j+c)^p
                     * f(|x,y - x_j,y_j|; d(m_j))
```

with `f` the Ogata spatial density and `d(m) = d0*exp(gamma*(m-mc))`. 8
parameters total (vs. temporal ETAS's 5): `mu, k0, alpha, c, p, d0, gamma, q`.

**Scoping decision made explicit** (this file previously flagged this as
needing a decision): the background rate `mu` stays a single homogeneous
scalar, exactly as in temporal ETAS -- NOT the spatially-varying rate
`background_rate.py` already produces. Jointly fitting a spatially-varying
background together with the triggering kernel is a materially larger
undertaking (see reasoning in `spatiotemporal_etas.py`'s docstring) and is
explicit future work, not silently approximated. The spatial *triggering*
extent (how far aftershocks spread) is real and independently fit-worthy on
its own.

**A real units bug was caught and fixed, not hidden**: `lambda(t,x,y)` is a
spatial density (events/day/km^2). The first implementation added `mu`
(events/day, unconverted) directly to that density-valued triggering term --
a units mismatch. Since realistic spatial-kernel density values are small
(~0.01/km^2 at plausible d/q scales) compared to `mu` of order 1, this let
the optimizer always collapse to `k0=0` with `mu` absorbing the entire rate,
*regardless of starting point, including when seeded exactly at the true
generating parameters* -- caught by directly comparing the negative
log-likelihood at the true parameters against a near-homogeneous fit before
and after the fix (before: true params scored *worse* than homogeneous,
which is essentially impossible for data actually generated by those
parameters; after: true params correctly scored better). Fixed by dividing
`mu` by the region area (`region_area_km2`) before adding it to the
density-valued term; the integral-of-intensity term needed no change (it
was already correct, since integrating a uniform density over the region
recovers the total rate regardless).

- `src/chile_oef/seismicity/spatiotemporal_etas.py::estimate_spatiotemporal_etas`.
  Same restart + `L-BFGS-B`-then-`Nelder-Mead` fallback strategy as temporal
  ETAS. Verified on an independently re-derived branching-process (Hawkes)
  simulation including a proper inverse-CDF spatial-offset sampler for the
  Ogata kernel. At `mu=1.0, k0=0.043, alpha=1.0, c=0.1, p=1.2, d0=5.0,
  gamma=0.5, q=1.8` (570 events, fixed seed), the fit is fully reproducible
  regardless of whether the optimizer is seeded at the true parameters or
  the default crude guess (both land at the identical log-likelihood,
  confirming a real, stable optimum, not seed-dependent luck), recovering
  `mu=1.35, k0=0.067, alpha=0.66, c=0.33, p=1.69, d0=8.37, gamma=0.68,
  q=3.86` -- correct order of magnitude and sign throughout, but visibly
  noisier than temporal ETAS's 5-parameter recovery, especially the
  correlated pairs `(c, p)` and `(d0, q)` which can trade off against each
  other. This is a real, expected property of the harder 8-parameter joint
  model, reflected honestly in per-parameter test tolerances (documented in
  the test itself), not a remaining bug or a precision claim.
- `db/models/seismicity.py::SpatiotemporalEtasEstimate` (append-only, same
  FK pattern as `TemporalEtasEstimate`, plus a mandatory bounding box and
  its computed `region_area_km2`) + Alembic migration `0011`.
  `SpatiotemporalEtasService.estimate_for_completeness_estimate` refuses
  (raises `ValueError`) a completeness estimate without a bounding box,
  rather than guessing a default region. When seeded from a declustering
  run, only `(c, p)` transfer from Modified Omori -- `k0`/`mu` are not
  meaningfully transferable across the units change described above. CLI:
  `chile-oef fit-spatiotemporal-etas --completeness-estimate-id <uuid> [--declustering-run-id <uuid>]`.
- Known limitation, not yet addressed: same O(n^2) likelihood scaling as
  temporal ETAS, now with 8 optimizer dimensions instead of 5 -- fitting
  time is correspondingly higher (a single restart on ~570 events takes on
  the order of 30-40 seconds). Documented the same way as every other
  O(n^2)/O(n*m) scaling note in this codebase.

Final gate on 2026-08-16: **102 tests passed** (96 prior + 6 new), Ruff,
`ruff format --check`, and `alembic check` all passed. Migration `0011`
applied cleanly against the real dev database. Full suite runtime is now
well over 2 minutes, driven by the ETAS family's restart costs -- flagged
again as worth addressing (e.g. a `slow`/`network`-style pytest marker to
separate these from the fast unit tests) before more slices are added, not
yet done in this session.

### Phase 5 started — seismic anomaly index (IAS) implemented and validated

Added on 2026-08-16, same session. First Phase 5 model
(docs/scientific-methodology.md item 6: "IAS as a non-probabilistic
activity-anomaly percentile"). Explicitly scoped to one component (of the
several docs/ias.md lists as candidates), not all of them at once, same
discipline as every prior slice this session.

- `src/chile_oef/seismicity/ias.py::estimate_ias`: `IAS = 100 * F(D)`
  (docs/ias.md), where `D` is a one-sided Poisson deviance comparing the
  observed event count in a recent evaluation window against the count an
  already-fit temporal ETAS model expects there, and `F` is `D`'s empirical
  percentile against a historical reference distribution built from earlier
  non-overlapping windows of the same length in the same catalog. "One-sided"
  means a quiet window (observed <= expected) scores deviance 0, not a
  symmetric anomaly -- IAS measures excess activity only, per docs/ias.md.
  The expected count for any window uses only events strictly before that
  window's start (same availability invariant, `forecast_time < event_time`,
  as everywhere else in this project) -- an event cannot contribute to the
  expectation of the same window it occurs in.
- **Scope explicitly limited to one component**: docs/ias.md lists ETAS
  count residuals, energy-proxy residuals, spatial concentration,
  persistence, and depth migration as candidate inputs, warning that
  "correlated components must not be double counted." Only the ETAS count
  residual is implemented; the others are named in the result's diagnostics
  as `components_not_yet_implemented`, not silently absent. Also explicitly
  not yet "network-epoch-aware" (docs/ias.md's stated design target): the
  historical reference distribution does not yet adjust for detection-
  capability changes across network epochs -- recorded as
  `network_epoch_aware: false` in diagnostics, a documented simplification.
- Verified with an injected-burst test: a synthetic catalog matching the
  fitted ETAS model closely for its whole history, then a 30-event burst
  added right at the evaluation window that the model does not expect.
  The burst scores `IAS >= 95` (effectively the most anomalous of ~48
  historical windows), while an ordinary window evaluated earlier in the
  *same* catalog (no injected burst) scores a typical, much lower
  percentile (~21 in the manual check that motivated the test) -- both
  computed through the identical historical-reference-distribution logic,
  isolating the burst's effect rather than differing setups.
- `db/models/seismicity.py::SeismicAnomalyIndexEstimate` (append-only,
  mandatory FK to the specific `TemporalEtasEstimate` whose fitted
  parameters defined the expected-count model) + Alembic migration `0012`.
  `IasEstimationService.estimate_for_temporal_etas_estimate` takes the ETAS
  estimate id and an explicit `evaluation_end_at` instant -- no "current"
  or "latest" default, matching every other service in this project.
  Refuses (raises `ValueError`) a `TemporalEtasEstimate` that did not
  converge, rather than computing IAS against undefined parameters. CLI:
  `chile-oef estimate-ias --temporal-etas-estimate-id <uuid> --evaluation-end-at <iso8601>`.
- Per docs/communication-policy.md, calibration_status is hard-fixed to
  `"uncalibrated_anomaly_index"` (not derived from any internal confidence
  metric) and nothing in this module's naming, diagnostics, or docstrings
  frames IAS as risk, hazard, or "an earthquake is coming" -- it is
  presented strictly as an observed-vs-expected-rate percentile.

Final gate on 2026-08-16: **108 tests passed** (102 prior + 6 new), Ruff,
`ruff format --check`, and `alembic check` all passed. Migration `0012`
applied cleanly against the real dev database. Unlike the ETAS family, IAS
itself is cheap to compute (no optimizer, pure arithmetic over precomputed
ETAS parameters), so this addition did not meaningfully increase suite
runtime.

### Forecast generation layer implemented and validated (prerequisite for Phase 6)

Added on 2026-08-16, same session, in response to a real gap found while
scoping Phase 6 (CSEP/pyCSEP evaluation): nothing in the repository actually
produced a registered `Forecast` matching docs/forecast-contract.md's
schema. Every prior estimator (Mc, GR, declustering, background rate,
Modified Omori, ETAS, IAS) is a statistical engine that produces
*estimates*, not a versioned, immutable, per-cell/per-magnitude-bin
forecast object with a validity window -- there was nothing concrete for a
CSEP-style evaluation to score against reality. This closes that gap before
Phase 6 begins, rather than attempting Phase 6 against a nonexistent
artifact.

- `config/forecast-specification.yaml` already existed from Phase 0
  (horizons `PT6H`/`P1D`/`P3D`/`P7D`, five non-overlapping magnitude bins
  `[3,4) [4,5) [5,6) [6,7) [7,inf)`, grid `chile_regular_0_1_v1`,
  estimability/immutability policy) but was never read by any code until
  now. `src/chile_oef/forecast/specification.py::load_forecast_specification`
  parses it into typed dataclasses -- no bin scheme or horizon list was
  invented; the Phase 0 design is used as written.
- `src/chile_oef/forecast/generation.py::generate_forecast_cells`: pure
  function computing, per grid cell and per magnitude bin, the expected
  event count and Poisson probability of at least one event
  (`1 - exp(-expected_count)`) over a validity window, from an already-fit
  `SpatiotemporalEtasParameters` and an already-fit Gutenberg-Richter
  `b_value`. Background is allocated to each cell proportional to its area
  (homogeneous mu, per the spatiotemporal ETAS scoping decision); each
  prior event's triggering contribution uses the same point-density-at-
  cell-center approximation `background_rate.py` already established and
  documented. Magnitude bins below the declared Mc are refused
  (`support_state="not_estimable"`) rather than computed with a formula
  that would silently exceed a valid probability -- forecast-contract.md's
  explicit "target threshold below Mc" not-estimable condition.
- Verified with three separate identities, not just a happy-path run: (1)
  with zero prior events, every cell's expected count is exactly
  proportional to its area (pure background, no triggering); (2) with
  `b=1.0`, each successive one-magnitude-unit-wide bin carries exactly
  1/10th the expected count of the previous one -- and the transition into
  the final *open-ended* bin is verified to be exactly 1/9, not 1/10 (a
  real, derived property of an open tail bin vs. a finite-width bin, caught
  while writing the test, not assumed); (3) summed over a grid padded well
  beyond the triggering kernel's reach, the total expected count across all
  cells and bins recovers the region-wide total (background + triggering,
  all magnitudes) to within the same ~1-2% edge-effect tolerance already
  established for `background_rate.py`'s and `spatiotemporal_etas.py`'s
  analogous mass-conservation checks.
- `db/models/forecast.py::ForecastRun` (append-only; mandatory FKs to the
  specific `SpatiotemporalEtasEstimate` and `GutenbergRichterEstimate` used,
  plus `SpatialGrid`; self-referential `supersedes_forecast_run_id` for
  recalculations, per forecast-contract.md's immutability rule -- "a
  recalculation creates a new run," never an update) and
  `ForecastCellMagnitudeBin` (one append-only row per cell per bin) +
  Alembic migration `0013`.
- `ForecastService.issue_forecast` refuses to mix a Gutenberg-Richter
  estimate and a spatiotemporal ETAS estimate that trace back to different
  `CompletenessEstimate` rows (different Mc/window lineage) -- verified
  with a dedicated integration test using two independently-converged fits
  over the *same* underlying catalog (so the refusal is specifically about
  lineage consistency, not just "one of the inputs happened to fail").
  Input catalog snapshot uses everything available as of `issued_at`
  (which may be later than, and see more data than, the cited Mc/b/ETAS
  fits' own original windows -- model/parameter-set version and input
  catalog snapshot are versioned independently, per forecast-contract.md).
  CLI: `chile-oef issue-forecast --spatiotemporal-etas-estimate-id <uuid>
  --gutenberg-richter-estimate-id <uuid> --issued-at <iso8601>
  --horizon-id <PT6H|P1D|P3D|P7D>`.
- Known limitation, not yet addressed: `calibration_status` is fixed to
  `"uncalibrated_point_forecast"` -- no parameter uncertainty from the
  underlying MLE fits is propagated into these probabilities yet (a point
  estimate only). Not yet conditioned on tectonic class or depth range,
  both named as optional forecast-contract.md dimensions. The real
  production grid (`chile_regular_0_1_v1`, 90,000 cells) x 5 magnitude bins
  means ~450,000 `ForecastCellMagnitudeBin` rows per issued forecast --
  correctness-tested only on small fixture grids so far; row volume at real
  scale is a noted, not yet exercised, consideration.

Final gate on 2026-08-16: **115 tests passed** (108 prior + 5 new unit +
2 new integration), full suite confirmed green end to end. Ruff, `ruff
format --check`, and `alembic check` all passed. Migration `0013` applied
cleanly against the real dev database.

Still not done for seismicity/forecasting: no public API endpoint for any
of these eleven models or the forecast layer -- everything is
CLI/service-only. The remaining IAS components (energy-proxy residual,
spatial concentration, persistence, depth migration) and network-epoch
awareness remain explicit future work, not silently implemented elsewhere.

### Phase 6 implemented and validated: walk-forward CSEP-style evaluation

Added on 2026-08-16, same session, immediately after the forecast
generation layer it scores. Implements every score name registered in
`config/evaluation-protocol.yaml` (binary: `log_loss`, `brier_score`,
`reliability`; count: `point_process_log_likelihood`, `deviance`,
`predictive_coverage`; spatial: `information_gain_per_event`,
`csep_spatial_test`; rare-event: `pr_auc`, `recall`, `false_alarm_rate`;
secondary: `roc_auc`, `precision`, `f1`) plus the classic CSEP consistency
battery (Zechar, Schorlemmer, Liukis, Yu, Euler, Werner & Jordan 2010):
Number, Magnitude, Spatial and joint Likelihood tests. `accuracy`, the
protocol's one explicitly prohibited primary score, is never computed.

- `src/chile_oef/evaluation/scoring.py`: pure scoring functions. Every
  function returns `None` (never a fabricated number) when a score is
  mathematically undefined for the given fold -- no positives for
  `pr_auc`/recall, no negatives for `roc_auc`/`false_alarm_rate`, zero
  observed events for `information_gain_per_event` -- the same
  `not_estimable` discipline used everywhere else in this project.
  Reliability is binned by predicted-probability *quantile*, not equal
  width: per-cell earthquake probabilities are typically 1e-6 to 1e-2, so
  equal-width bins over `[0, 1]` would leave every bin but the first
  empty. `predictive_coverage` is documented as systematically
  conservative (>= its nominal level) for discrete counts, not
  miscalibrated -- a real property of equal-tailed Poisson intervals, not
  a bug, caught while writing its own verification test.
- `src/chile_oef/evaluation/csep_tests.py`: the N-test is evaluated
  analytically (the sum of independent Poisson variables is itself
  Poisson, no simulation needed). The M-test and S-test share one
  machinery: conditioning independent Poisson counts on their known total
  is *exactly* a multinomial distribution over the normalized rates (not
  an approximation) -- verified independently by brute-force rejection
  sampling from the underlying Poissons, compared against
  `numpy.random.Generator.multinomial`. The L-test simulates full
  (unnormalized) catalogs from the forecast rates.
- Verification methodology matches every other estimator this session: the
  flagship check is that under the null hypothesis (observed data really
  drawn from the forecast), each simulation-based test's reported quantile
  is uniformly distributed on `[0, 1]` -- the defining property of a valid
  probability-integral-transform test statistic, checked over 250
  independent trials for the L-test and S-test, independent of anything in
  their own implementation. Separately, each test is checked to correctly
  detect a grossly wrong forecast (quantile near 0, `consistent_at_alpha`
  False) on deliberately mismatched synthetic cases.
- `src/chile_oef/evaluation/replay.py::run_walk_forward_evaluation`:
  issues one real, persisted `ForecastRun` per issue time across
  `[walk_forward_start, walk_forward_end)` via the *same*
  `ForecastService.issue_forecast` every other forecast uses (no
  evaluation-only code path that could silently diverge from what
  actually gets issued), scored against events actually observed once the
  catalog has had `adjudication_delay` to mature
  (docs/backtesting.md: "adjudicated evaluation occurs after the
  registered catalog-maturation delay"). `information_gain_per_event`
  compares the model forecast to a homogeneous-Poisson reference
  (the same fitted spatiotemporal ETAS parameters with `k0` forced to 0,
  background only, computed but never persisted as a `ForecastRun`) --
  this reference is exactly stage 1 of
  docs/scientific-methodology.md's scientific progression ("Empirical
  base-rate and homogeneous Poisson"), which had never existed as its own
  artifact until this comparison needed one.
- Point-to-cell assignment (`_cell_id_for_point`) is analytic, matching
  `chile_oef.tectonics.grid.iter_cells`'s deterministic id scheme exactly,
  rather than a spatial query -- correct by construction for any regular
  grid built by `GridService`, with no separate id-matching logic to drift
  out of sync.
- `ForecastService` was refactored (no behavior change; the full existing
  forecast-layer test suite still passes unmodified) to expose
  `prepare_generation_inputs` as its own method, separating "resolve
  lineage + fetch the availability-safe prior catalog" from "generate and
  persist" -- the walk-forward harness reuses it to build the homogeneous-
  Poisson reference model without duplicating the catalog-fetch and
  lineage-consistency logic `issue_forecast` already has.
- Block-bootstrap uncertainty (`config/evaluation-protocol.yaml`:
  `resampling: {method: block_bootstrap, blocks: [time, earthquake_sequence]}`):
  each walk-forward fold is already one non-overlapping time block by
  construction (the embargo/step design), so resampling folds with
  replacement *is* the registered "time" block bootstrap -- no separate
  block-partitioning step was needed. "earthquake_sequence"-block
  resampling is explicitly **not implemented** (documented in every
  `EvaluationRun.diagnostics_json`, not silently dropped) -- it would
  require grouping the evaluation catalog by declustering family across
  the whole run, a materially larger piece of scope deferred rather than
  half-built.
- `db/models/evaluation.py::EvaluationRun` (append-only; one row per
  walk-forward execution, mandatory FKs to the specific
  `SpatiotemporalEtasEstimate` and `GutenbergRichterEstimate` under test
  and the `SpatialGrid` used; `aggregate_scores_json` holds the
  bootstrapped point estimate + CI per scalar score, plus per-CSEP-test
  fraction-consistent-at-alpha summaries) and `EvaluationFoldScore`
  (append-only; one row per issue time, mandatory FK to the exact
  `ForecastRun` it scored, `scores_json` holding every per-fold scalar and
  CSEP test result) + Alembic migration `0014`. CLI:
  `chile-oef run-walk-forward-evaluation --spatiotemporal-etas-estimate-id
  <uuid> --gutenberg-richter-estimate-id <uuid> --walk-forward-start
  <iso8601> --walk-forward-end <iso8601> --step-seconds <n> --horizon-id
  <PT6H|P1D|P3D|P7D> --adjudication-delay-seconds <n>`.
- Real-data honesty, not just a green test suite: this harness is
  validated here against a synthetic branching-process catalog (the same
  independently re-derived simulator used throughout Phase 3/4), the same
  way every other estimator in this project was first validated. At the
  time this section was written, it had not yet been run against a
  genuine multi-decade Chilean seismicity history -- see the "Bulk
  historical USGS ingestion" section immediately below, added later the
  same session, which closes the raw-data half of that gap. Running the
  Mc/GR/declustering/ETAS/forecast pipeline itself against that real
  catalog, and then re-running Phase 6 against it, is still explicit next
  work, not done as part of this slice.

Final gate on 2026-08-16: **145 tests passed** (115 prior + 29 new unit +
1 new integration), full suite confirmed green end to end. Ruff, `ruff
format --check`, and `alembic check` all passed. Migration `0014` applied
cleanly against the real dev database.

### Bulk historical USGS ingestion implemented, validated, and actually run

Added on 2026-08-16, same session, in direct response to Phase 6's own
"real-data honesty" gap above: only two real USGS events had ever been
ingested into this repository (Phase 1's original smoke test). No
walk-forward evaluation, and no 27F Maule case study specifically, can be
honestly called prospective against real Chilean seismicity without a real
historical catalog behind it.

- `src/chile_oef/ingestion/historical_backfill.py::plan_time_partitions`:
  a pure, injectable-count-function partitioner that recursively bisects a
  time range until every leaf slice's real event count is at/below a
  declared cap (default 15,000, below the FDSN service's real 20,000-
  result limit, leaving headroom for events landing between a slice's
  `count()` check and its `fetch()`). Verified with a synthetic event-
  density model, independent of any real adapter: full coverage with no
  gaps or overlaps, every leaf under the cap, adaptive finer partitioning
  of a simulated dense sub-region versus a quiet one, and a hard refusal
  (not silent truncation) if a slice still exceeds the cap at the
  declared minimum granularity.
- `run_usgs_historical_backfill` orchestrates this over the existing,
  unmodified `UsgsFdsnAdapter` and `IngestionService` (no new ingestion
  code path that could silently diverge from the one single-slice
  ingestion already used and tested). Two properties a real multi-request
  historical pull actually needs, both verified with a fake adapter
  factory (no real network in the automated test suite): resumable (a
  second run against the same range skips every slice already recorded
  succeeded in the new `HistoricalBackfillSlice` table, verified by
  running the orchestrator twice and confirming zero re-fetches and zero
  duplicate `EventRevision` rows) and failure-isolated (a slice that fails
  on every retry attempt is recorded failed and reported, without
  aborting ingestion of every other slice in the run).
- `db/models/backfill.py::HistoricalBackfillSlice` + Alembic migration
  `0015`. Resumability is matched on source, exact time range, magnitude
  floor and bounding box stored as real columns -- not by parsing
  `IngestionRun.request_url` query strings, which would be fragile against
  any change in how those parameters happen to get URL-encoded.
- CLI: `chile-oef backfill-usgs-historical --start <iso8601> --end
  <iso8601> [--min-magnitude <m>] [--min/max-latitude/longitude ...]`.
- **Actually run against the live USGS API this session, not just
  tested against fakes.** A one-month pilot (2024-06 through 2024-07, 85
  events) was run first against the real service to prove the whole path
  end to end, then re-run to confirm real resumability (second run:
  `succeeded=0 skipped=1`). The full range USGS ComCat actually has for
  Chile, `1964-01-01` through `2026-08-16` (this session's date), was then
  backfilled for real: **9 slices, all succeeded, 0 failed, 74,384 events
  seen, 74,297 new `EventRevision` rows inserted** (the small gap is
  duplicate/boundary events the existing `revision_hash` dedup correctly
  collapsed, not a bug in this new code). The real total volume turned out
  far smaller than the "many hours, many thousands of requests" this
  section originally worried about when scoping the work -- USGS ComCat's
  own Chile-region catalog is on the order of 10^4-10^5 events, not larger,
  because ComCat is materially less complete for small local events than
  CSN's own denser regional network would be (a real, load-bearing
  limitation to keep in mind for any Mc estimate run against this
  ingested catalog: it inherits ComCat's own regional completeness, not
  CSN's). The real Maule earthquake (2010-02-27 06:34 UTC, Mw 8.8, `mww`)
  and its aftershock sequence are present and verified queryable in the
  ingested catalog -- the 27F case study docs/backtesting.md names is now
  actually possible to run, though nothing in this slice ran it yet.
- Still not done: this backfill only used `usgs_comcat`
  (`config/source-registry.yaml`'s one already-`enabled: true`,
  already-legally-clear source). `csn_daily`, `csn_compiled_catalog`, and
  `potin_1982_2020` remain `enabled: false` pending the license/contact
  review `docs/data-sources.md` already requires -- none of them were
  touched, silently enabled, or worked around. No Mc/Gutenberg-
  Richter/declustering/ETAS/forecast/evaluation model has been re-run
  against this real catalog yet; every scientific-slice validation to
  date still refers to synthetic or 2-event smoke-test data. Raw content
  is stored locally under `data/raw` (excluded from Git per
  docs/data-governance.md's redistribution policy) and is not part of
  this or any commit.

Final gate on 2026-08-16: **7 new tests passed** (5 unit + 2 integration,
on top of the 145 already passing), full suite (152 total) confirmed
green. Ruff, `ruff format --check`, and `alembic check` all passed.
Migration `0015` applied cleanly against the real dev database, which now
also holds the real ingested catalog described above.

### First real-catalog scientific pipeline run, and a genuine bitemporal-availability finding

Added on 2026-08-16, same session, in response to a request to turn this
work into a live web dashboard -- which needs real fitted parameters and
a real forecast to show, not just a real catalog. Ran the full chain once
against the real ingested USGS catalog, all through the existing
CLI/services, no new code:

- Mc (Entire Magnitude Range, the registered primary estimator): window
  2005-01-01..2015-01-01 (chosen to bracket the 27F Maule mainshock),
  magnitude type `mb` (the single largest homogeneous magnitude-type
  sample in the real catalog, 25,987 of 74,384 rows; `md`, `ml`, and
  several `mw*` variants each have far fewer rows and were not mixed in,
  per completeness.md's per-magnitude-type requirement). Result:
  `mc=4.97`, `event_count=7493`, `support_state=supported`. This Mc is
  notably higher than a CSN-network local estimate would likely be --
  expected and explicitly already documented in the ingestion section
  above: ComCat's own regional completeness for Chile is materially
  worse than CSN's denser network would give.
- Gutenberg-Richter (Aki MLE): `b=2.13 (SE 0.098)` over 483 events at/above
  Mc. Unusually high versus typical regional b~0.7-1.1 -- reported as the
  real, uncalibrated MLE output over this specific window/magnitude-type
  slice, not adjusted or investigated further (a real avenue for future
  scrutiny -- e.g. binned-magnitude MLE correction -- explicitly not
  attempted here, not hidden).
- Declustering: 483 events classified, 183 background / 300 triggered.
- Background rate: estimated over the real, full-scale production grid
  `chile_regular_0_1_v1` (90,000 cells) for the first time -- previously
  only exercised on small fixture grids.
- Spatiotemporal ETAS: converged (6/6 restarts), `mu=0.023/day, k0=0.027,
  alpha=3.13, c=0.0044d, p=1.048, d0=15.4km, gamma=0.47, q=1.64`.
- A real forecast was issued (`issue-forecast`, horizon P7D, issued at
  the actual current time) over the full 90,000-cell grid x 5 magnitude
  bins -- **450,000 `ForecastCellMagnitudeBin` rows**, the real-scale row
  volume the forecast-generation-layer section above flagged as "not yet
  exercised." It completed; row volume at real scale is no longer an
  open question for the generation step itself (API/serving performance
  at that scale is still untested, see below).

**A genuine, load-bearing finding, not a bug**: a Phase 6 walk-forward
evaluation was attempted against this same real catalog and deliberately
not completed, because the bitemporal invariant this whole project is
built around correctly refuses to allow it. Every row from this bulk
backfill has `available_at` set to the actual ingestion moment (today),
not the historical event date -- the only honest choice, since we did not
actually have this data at any earlier historical moment
(docs/backtesting.md: "labeled pseudoprospective unless archival source
revisions and receipt times can be recovered"; USGS's own per-event
`updated` timestamp is captured separately as `source_updated_at` and was
deliberately *not* substituted in as `available_at`, which would have
been exactly the kind of retroactive availability fabrication this
architecture exists to prevent). Concretely verified: issuing a forecast
"now" sees 626 real prior events; the identical call with `issued_at` set
two days in the past sees **zero** prior events (confirmed directly via
`prepare_generation_inputs`), because no backfilled row's `available_at`
is ever earlier than today. A walk-forward fold issued in the past against
this catalog would therefore score an artificially empty-catalog forecast,
not a real historical one -- and a fold issued in the future has no
observed outcome yet to score against. **Genuine prospective Phase 6
evaluation against this real catalog cannot begin before real time has
elapsed from today's ingestion moment forward**; this is not a gap to
close with more code, it is what "prospective" actually requires, and the
system correctly refuses to fake it.

### First public read-only API + static dashboard, serving the real run above

Added on 2026-08-16, same session, in response to a request to put this
work in front of real visitors as a web app on etemen.cl (ETEMEN's
existing site, `forja-web`). Closes the "no public API endpoint for any
of these eleven models or the forecast layer" gap flagged repeatedly
above -- but deliberately only the read-only slice a public showcase
needs, not a general CRUD API.

- New endpoints (`src/chile_oef/app/api/routes.py`,
  `src/chile_oef/app/api/schemas.py`): `GET /v1/catalog/summary`
  (aggregate stats + top-magnitude events over the real ingested
  catalog), `GET /v1/forecasts` and `GET /v1/forecasts/{id}` (cell
  detail, one magnitude bin at a time -- a real run is 90,000 cells x 5
  bins = 450,000 rows, far more than a browser should ever fetch at
  once), and `GET /v1/seismicity/model-summary` (the most recently
  converged spatiotemporal ETAS fit and the exact Gutenberg-Richter/
  completeness estimates it cites). All reuse existing models directly;
  no new persistence.
- A real bug caught before it shipped: `forecast_run_detail`'s first
  version defaulted to the *lowest* registered magnitude bin, which is
  always empty whenever Mc exceeds the bin's lower edge (exactly the
  case for the real `mb` fit above, Mc=4.97 > bins [3,4) and [4,5)) --
  forecast-contract.md's own "target threshold below Mc is
  not_estimable" rule guarantees zero estimable cells there. Fixed to
  default to the smallest bin at/above the run's own `reference_magnitude`
  instead; a dedicated integration test
  (`tests/integration/test_dashboard_api.py`) asserts the default
  selection is always `>= mc`, specifically so this class of bug cannot
  regress silently.
- `uvicorn` was missing from `pyproject.toml` entirely (the README's own
  "start the API" instructions never actually worked without a global
  install) -- added as a real dependency. CORS middleware added
  (`app/main.py`, GET-only, origins configurable via
  `CHILE_OEF_CORS_ALLOWED_ORIGINS`, defaulting to `etemen.cl` and
  localhost).
- `Settings.database_url` now normalizes a bare `postgres://` or
  `postgresql://` connection string (what Render and Heroku-style managed
  Postgres actually hand out) to the explicit `postgresql+psycopg://`
  scheme this app's driver needs -- verified with unit tests
  (`tests/unit/test_settings.py`), needed before this app can run against
  any hosted database.
- Static dashboard added to `forja-web` (ETEMEN's existing site,
  separate repo) at `/chile-oef/`, in the site's own dark design system
  (no new framework): live forecast map (canvas, no map-tile dependency),
  model-parameter card, real catalog stats with the 27F Maule earthquake
  highlighted, and an explicit section explaining the bitemporal-
  availability finding above -- framed as a demonstration of rigor, not
  hidden. Linked from ETEMEN's main nav, footer, and a new
  "Investigación" section on the homepage, kept visually and textually
  distinct from the commercial Nexo/indago product cards (CHILE-OEF is
  not for sale). All API field names used by the dashboard's JS were
  cross-checked field-by-field against the real running API (no browser
  available in this environment to visually confirm rendering -- noted
  as an open verification gap, not silently claimed as done).
- `render.yaml` added (Render Blueprint, free tier: a Postgres database
  plus this API as a Python web service, mirroring `forja-web`'s existing
  deployment pattern) but **not yet deployed** -- creating the actual
  GitHub repo, Render database, and Render web service are real,
  externally-visible account actions not taken without the user directly
  in the loop. See "Exact next work" for what remains.

156 tests passing (153 prior + 3 new settings-normalization unit tests;
the dashboard API integration test was already included in the 153).
Ruff, `ruff format --check`, and `alembic check` all clean.

## Verified static data releases

### USGS Slab2 South America

- Official release DOI: <https://doi.org/10.5066/F7PV6JNV>
- Method paper: Hayes et al. (2018), <https://doi.org/10.1126/science.aat4723>
- ScienceBase item: `5aa41473e4b0b1c392eaaf2d`
- Release identifier: `sam_02.23.18`
- Grid spacing: 0.05°; original longitude 0–360; original depth negative down.
- License recorded as US public domain.
- Pinned assets and locally verified values:

| Asset | Bytes | SHA-256 |
|---|---:|---|
| depth | 14,339,837 | `0522c999fcd3f80422407e0f6bdb4cb1ce09bd2cf1f13d68c2b169c26762bbca` |
| dip | 14,134,592 | `dcdd1c10ceaf5423a9f4ffbd7a238525f24112d66a83e2e62ce9ae7576c6411c` |
| strike | 14,136,413 | `c138d970788e9c1d4efa95a25ce0b62472cc6c3f53457adfb48db5a3536d7422` |
| thickness | 14,134,504 | `0d46977fb483ddc8553eac14db67f9dca51a4cb7e262f2b4e7fad6d73809f604` |
| uncertainty | 14,133,924 | `e21d3d7b65f7da0be5cb6952ec901d359da514d20e02428495c579d798a971dc` |

Exact download URLs are in `config/tectonic-assets.yaml`; never replace them
without recording a new release and re-verifying hashes.

### Chile Active Faults Database (CHAF)

- PANGAEA release DOI: <https://doi.org/10.1594/PANGAEA.922241>
- Description paper: Maldonado et al. (2021),
  <https://doi.org/10.1038/s41597-021-00802-4>
- License: CC-BY-4.0; attribution is required.
- Shapefile contains 958 mapped fault strands, grouped into 17 systems.
- It represents mapped surface traces, not 3-D seismogenic fault surfaces and not
  a complete census of every active Chilean fault.
- Pinned ZIP: 253,556 bytes; SHA-256
  `e42fd56cd0dddec384e9dcbede0fc801e30d3f19ba0aa9987c3c832148ead59b`.
- Direct URL is in `config/tectonic-assets.yaml`.

## Exact next work

The following should be done next, in this order:

1. ~~Initialize Git~~ — done 2026-08-16 (commit `eea1333`, see Repository and
   environment above).
2. ~~Design Phase 3 as a small scientific slice~~ — done 2026-08-16: catalog
   selection contract, estimability/support bands, and regression/synthetic
   fixtures exist (see Phase 3 section above).
3. ~~Implement Goodness-of-Fit, then Entire Magnitude Range with bootstrap~~
   — done 2026-08-16. All three Mc estimators from docs/completeness.md now
   exist: Maximum Curvature and Goodness-of-Fit (`role=diagnostic`), Entire
   Magnitude Range (`role=primary`, the one actually registered as primary).
   `numpy`/`scipy` are now real dependencies.
4. ~~Implement Gutenberg–Richter b-value MLE with uncertainty~~ — done
   2026-08-16, resolved as re-estimate independently above a declared Mc
   (see Phase 3 continued section above), not reuse of EMR's internal
   byproduct.
5. ~~Add fixed historical fixtures and walk-forward tests~~ — done for
   Gutenberg-Richter 2026-08-16
   (`test_gutenberg_richter_excludes_late_arriving_revision_above_mc`). Not
   yet extended to declustering specifically; the declustering integration
   test verifies correctness on a real-ingested catalog but does not yet
   have a dedicated late-arriving-revision walk-forward case.
6. ~~Declustered background, smoothed background rate, and Modified
   Omori~~ — all done 2026-08-16 (see Phase 3 continued sections above).
7. ~~Temporal ETAS, then spatiotemporal ETAS~~ — both done 2026-08-16 (see
   Phase 4 sections above). The scoping decision this item used to flag as
   open (space added to the same joint MLE, homogeneous background) is now
   resolved and documented, along with a real units bug caught and fixed
   during validation. Spatially-varying background jointly fit with the
   ETAS triggering kernel (deferred by that scoping decision) remains open
   future work, not scheduled next by default.
8. ~~IAS (one component: ETAS count residual)~~ — done 2026-08-16 (see
   Phase 5 started section above). Remaining IAS components from
   docs/ias.md (energy-proxy residual, spatial concentration, persistence,
   depth migration) and network-epoch awareness are explicit future work,
   not next by default.
9. ~~Forecast generation layer~~ — done 2026-08-16 (see "Forecast
   generation layer implemented and validated" section above). A real gap
   found while scoping Phase 6: nothing previously produced a
   forecast-contract.md-shaped `ForecastRun`. Remaining forecast-layer
   gaps (parameter-uncertainty propagation, tectonic-class/depth
   conditioning, spatially-varying background) are explicit future work,
   not scheduled next by default.
10. ~~CSEP/pyCSEP evaluation and walk-forward replay (Phase 6)~~ -- done
    2026-08-16 (see "Phase 6 implemented and validated" section above):
    the full config/evaluation-protocol.yaml score registry, the classic
    CSEP N/M/S/L consistency tests, and time-block bootstrap uncertainty,
    wired through `run_walk_forward_evaluation` and validated against a
    synthetic catalog.
11. ~~Bulk historical USGS ingestion~~ -- done 2026-08-16 (see "Bulk
    historical USGS ingestion" section above): 74,384 real events,
    1964-01-01 through 2026-08-16, actually ingested from the live USGS
    API, including the 27F Maule mainshock and aftershock sequence. **Next
    by default now**: run the Mc / Gutenberg-Richter / declustering /
    background-rate / ETAS / forecast pipeline against this real catalog
    for the first time (every fit to date has used synthetic fixtures or
    the original 2-event smoke test), then re-run Phase 6 against those
    real fits -- only then can the 27F case study and the "hundreds or
    thousands of no-megathrust windows" docs/backtesting.md requires
    alongside it actually be attempted. `csn_daily`,
    `csn_compiled_catalog` and `potin_1982_2020` remain deliberately
    `enabled: false` pending the license/contact review
    docs/data-sources.md requires -- not silently worked around.

## Known technical risks and decisions still to verify

- Slab2 currently parses complete text assets into multiple dictionaries before
  retaining the Chile bounding box. The real run peaked near 318 MB; streaming or
  staged COPY is a worthwhile later optimization but is not a correctness blocker.
- ScienceBase was intermittently slow. Four-attempt exponential retry and verified
  local import exist; permanent 404 responses are not retried.
- CHAF has one repeated `F_id` among 958 records. Migration `0004` correctly uses
  the stable shapefile record ordinal as trace identity while preserving `F_id`.
- CHAF dip/rake fields include `~90`, ranges and qualitative terms. Originals and
  interpretation status are retained; no arbitrary range midpoint is generated.
- `FaultRepository.nearest` geography distance passed the real PostGIS integration
  test, but remains horizontal distance to a mapped surface trace only.
- Migration `0003` uses `postgresql_nulls_not_distinct=True`, so the supported
  PostgreSQL deployment must remain version 15+ (the project compose image is
  PostgreSQL 17). Generated DDL currently passes `alembic check`.
- `ready_release` intentionally fails if more than one release is ready rather than
  silently selecting one. Before multiple releases are introduced, require an
  explicit release ID in CLI/API/model runs.
- Regular 0.1° cells are the evaluation baseline. A coarser 0.2° grid can be a
  declared alternative. Quadtree/adaptive grids are experimental and require
  support constraints plus area-correct likelihood evaluation.
- Latitude/longitude interpolation is sufficient for this first raster lookup but
  does not create a triangulated 3-D slab. Do not label its derived distance as a
  true Euclidean closest-surface distance.

## Later roadmap (do not skip gates)

1. Phase 3: spatial/temporal Mc with uncertainty; Gutenberg–Richter MLE and
   uncertainty; declustered/smoothed background; Modified Omori sequence fits.
2. Phase 4: temporal ETAS first, then space-time ETAS. Version every parameter fit
   and preserve optimizer diagnostics/stability checks.
3. Phase 5: IAS anomaly engine, always separate from forecast probability and
   explainable by contribution.
4. Phase 6: CSEP/pyCSEP evaluation, walk-forward replay, number/spatial/magnitude
   and likelihood tests, Brier/log score/calibration/information gain.
5. Phase 7: RF/XGBoost challengers only after baselines; explicit targets and
   availability-safe features; no accuracy-only reporting.
6. Phase 8+: GNSS, then Coulomb/rate-state research, calibrated ensemble and
   real-time dashboard. These remain experimental until prospectively validated.

The special 27F experiment must freeze the catalog at 2010-02-26 23:59 Chile using
what was actually available then. It is one case study, never the sole evidence;
hundreds or thousands of no-megathrust windows must be scored as well.

## Definition of done for a scientific slice

A slice is not complete until:

- inputs have an official/reviewed source, license, release/version, retrieval time,
  hash and raw archive;
- transforms are deterministic and parameterized;
- `available_at` and all model/data versions are retained;
- unit, data-contract, integration and scientific regression tests pass;
- uncertainty and not-estimable states are explicit;
- API language follows `docs/communication-policy.md`;
- documentation states recommended, experimental and not recommended components;
- this continuity file records what actually passed, not what was merely planned.
