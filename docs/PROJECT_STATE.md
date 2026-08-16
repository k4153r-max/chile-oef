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

Still not done for seismicity: no forecast, no public API endpoint for any
of these five models (three Mc estimators + GR + declustering) --
everything so far is CLI/service-only. Smoothed adaptive-kernel background
rate estimation over the background subset this declustering step produces,
and Modified Omori for the triggered subset, are the next two pieces before
ETAS (docs/scientific-methodology.md's progression).

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
6. ~~Declustered background~~ — nearest-neighbor declustering done
   2026-08-16 (see Phase 3 continued section above). Remaining: (a)
   smoothed adaptive-kernel background rate estimation over the resulting
   background subset (Helmstetter, Kagan & Jackson 2007 -- for each grid
   cell, sum Gaussian kernels centered on background events with
   per-event adaptive bandwidth from k-nearest-neighbor spacing; the
   existing `spatial_grids`/`seismic_cells` tables from Phase 2 are the
   natural place to evaluate this), and (b) Modified Omori-Utsu sequence
   fits over the triggered subset (grouped by inferred parent, per the
   `parent_event_revision_id` linkage `EventDeclusteringClassification`
   already records). Temporal ETAS follows those two baselines.

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
