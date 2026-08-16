# CHILE-OEF

Chile Operational Earthquake Forecasting Research Platform is an experimental,
auditable platform for probabilistic earthquake-occurrence forecasting in Chile.

It is not a deterministic earthquake predictor, an early-warning system, or an
official civil-protection product. Its purpose is to measure whether observable
seismic, tectonic and, later, geodetic information improves forecasts over
established statistical baselines.

## Current scope

The repository contains the Phase 0 scientific contracts, the Phase 1 catalog
foundation, the Phase 2 tectonic foundation, the Phase 3 seismicity gate
(magnitude of completeness, Gutenberg-Richter, declustering, background rate,
Modified Omori), Phase 4 (temporal and spatiotemporal ETAS), and a first
Phase 5 slice (IAS):

- immutable raw-source artifacts;
- bitemporal source event revisions;
- quality flags and provenance;
- immutable, content-addressed dataset manifests;
- probabilistic candidate deduplication without deleting originals;
- read-only catalog API;
- historical replay ordered by data availability.
- a versioned regular 0.1° evaluation grid;
- checksum-pinned Slab2 and CHAF ingestion;
- bilinear Slab2 sampling and CHAF surface-trace distances;
- an explicitly uncalibrated tectonic classification baseline;
- availability-safe magnitude catalog selection and three magnitude-of-
  completeness estimators with configured estimability bands: Maximum
  Curvature and Goodness-of-Fit (diagnostic cross-checks) and Entire
  Magnitude Range with bootstrap uncertainty (the registered primary
  estimator, Ogata & Katsura 1993);
- Gutenberg-Richter b-value (Aki 1965 MLE with Shi & Bolt 1982 uncertainty),
  always citing the specific completeness estimate whose Mc it used;
- nearest-neighbor declustering (Baiesi & Paczuski 2004; Zaliapin &
  Ben-Zion 2013), separating background from triggered events using the
  Gutenberg-Richter estimate it cites;
- smoothed adaptive-kernel background rate (Helmstetter, Kagan & Jackson
  2007) over a declustering run's background subset, evaluated on a Phase 2
  grid;
- Modified Omori-Utsu aftershock sequence fits (Ogata 1983) over each
  triggered family a declustering run identifies;
- temporal ETAS (Ogata 1988), a joint 5-parameter maximum-likelihood fit
  over the entire catalog above a declared Mc;
- spatiotemporal ETAS, adding an Ogata (1998) isotropic power-law spatial
  triggering kernel (8 parameters total; background rate stays
  homogeneous by deliberate scoping decision, see docs/PROJECT_STATE.md);
- a seismic anomaly index (IAS, one component: ETAS count residual as a
  historical percentile) -- an activity-anomaly measure, never a forecast
  probability or hazard statement;
- a forecast generation layer (docs/forecast-contract.md): immutable,
  versioned grid-cell x magnitude-bin forecasts from an already-fit
  spatiotemporal ETAS model and Gutenberg-Richter b-value, over the
  horizons and magnitude bins already registered in
  config/forecast-specification.yaml;
- walk-forward CSEP-style evaluation (docs/backtesting.md,
  config/evaluation-protocol.yaml): issues and scores real forecast runs
  across a historical window against what was actually observed, with the
  full registered score set (log loss, Brier score, reliability,
  point-process log-likelihood, deviance, predictive coverage, information
  gain per event, PR-AUC, ROC-AUC and threshold scores) plus the classic
  CSEP Number/Magnitude/Spatial/Likelihood consistency tests and
  time-block bootstrap uncertainty -- validated so far against synthetic
  catalogs only;
- a resumable, failure-isolated bulk historical USGS ingestion
  (`chile-oef backfill-usgs-historical`), actually run this session: the
  real USGS ComCat catalog for Chile, 1964-01-01 through 2026-08-16
  (74,384 events, including the 27F Maule mainshock and its aftershock
  sequence), is ingested and queryable.

No seismicity/forecast/evaluation model has been re-run against that real
catalog yet -- every fit to date used synthetic fixtures or the original
2-event smoke test; that is the next step, not something this scope
claims to have done. IAS's remaining components and ML are deliberately
not implemented yet. The tectonic class uncertainty masses are not
calibrated forecast probabilities.

## Local development

1. Copy `.env.example` to `.env` if local overrides are needed.
2. Start PostGIS with `docker compose up -d db`.
3. Create a virtual environment and install `.[dev]` (the existing environment can
   use `.venv/bin/uv` when `uv` is not globally available).
4. Run `alembic upgrade head`.
5. Run `pytest` and `ruff check .`.
6. Start the API with `uvicorn chile_oef.app.main:app --reload`.

Create a reproducible input snapshot with, for example,
`chile-oef create-dataset --dataset-id catalog --version 2026-08-16 --as-of
2026-08-16T23:59:59Z`. Dataset selection is made on `available_at`, not origin
time.

See `docs/scientific-methodology.md`, `docs/forecast-contract.md`, and
`docs/data-sources.md` before adding a scientific model.

## Scientific disclaimer

CHILE-OEF es una plataforma experimental de investigación que analiza patrones
estadísticos de actividad sísmica. No predice terremotos de forma determinista y
no reemplaza información oficial del Centro Sismológico Nacional, SENAPRED ni
otras autoridades.
