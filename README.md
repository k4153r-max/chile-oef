# CHILE-OEF

Chile Operational Earthquake Forecasting Research Platform is an experimental,
auditable platform for probabilistic earthquake-occurrence forecasting in Chile.

It is not a deterministic earthquake predictor, an early-warning system, or an
official civil-protection product. Its purpose is to measure whether observable
seismic, tectonic and, later, geodetic information improves forecasts over
established statistical baselines.

## Current scope

The repository contains the Phase 0 scientific contracts, the Phase 1 catalog
foundation, the Phase 2 tectonic foundation, and a first Phase 3 magnitude-of-
completeness slice:

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
  Gutenberg-Richter estimate it cites.

Smoothed background rate, Omori, ETAS, IAS and ML are deliberately not
implemented
yet. The tectonic class uncertainty masses are not calibrated forecast
probabilities.

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
