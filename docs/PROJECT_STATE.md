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

Explicitly not done in this slice: Goodness-of-Fit cross-check, Entire
Magnitude Range with bootstrap uncertainty (the actual primary estimator),
spatial adaptive-neighborhood Mc (this slice only supports a fixed bounding
box or no spatial filter at all), tectonic-class-conditioned Mc, and any API
endpoint (only CLI exists so far). None of these should be assumed
implemented just because this section exists.

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
3. Implement Goodness-of-Fit as the second Mc cross-check, then Entire
   Magnitude Range with bootstrap uncertainty as the actual primary estimator
   registered in docs/completeness.md. Maximum Curvature (done) stays
   diagnostic-only; do not promote it to primary. Reuse
   `catalog_selection.fetch_magnitude_catalog` rather than re-deriving
   availability-safe selection.
4. Implement Gutenberg–Richter b-value MLE with uncertainty and a declared Mc
   (from step 3, not Maximum Curvature); refuse under-supported cells rather
   than returning unstable values.
5. Add fixed historical fixtures and walk-forward tests that demonstrate no event
   with `available_at > catalog_as_of` enters a feature or fit — the pattern in
   `tests/integration/test_completeness_pipeline.py::test_availability_invariant_excludes_late_arriving_revision`
   can be extended rather than rebuilt.
6. Only after Mc/GR gates pass, proceed to declustered/smoothed background and
   Modified Omori. Temporal ETAS follows those baselines.

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
