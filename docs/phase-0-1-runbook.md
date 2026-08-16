# Phase 0–2 runbook

## Scope and status

This release implements scientific contracts, the catalog foundation and the
tectonic foundation. It does not implement Mc, Gutenberg–Richter, Omori, ETAS,
IAS, or a public earthquake-occurrence forecast. The tectonic rule baseline is
explicitly uncalibrated.

## Start and migrate

```bash
docker compose up -d db
uv sync --extra dev
uv run alembic upgrade head
uv run chile-oef sync-sources
```

If `uv` is only installed inside the project environment, replace `uv` with
`.venv/bin/uv` or run the executables directly from `.venv/bin`.

`alembic check` must report no new upgrade operations. PostGIS extension tables
are intentionally excluded from application-schema comparison.

## Ingestion

Low-latency USGS feed:

```bash
uv run chile-oef ingest-usgs-feed
```

Bounded historical slice:

```bash
uv run chile-oef ingest-usgs-fdsn \
  --start 2026-08-09T00:00:00Z \
  --end 2026-08-17T00:00:00Z \
  --min-magnitude 2.5
```

The FDSN adapter first checks the count endpoint and rejects slices above
20,000 events. Both integer text and the observed JSON count response are
accepted. The default rectangle is 15–60°S, 62–82°W. A zero-record global-feed
run is valid when no event lies inside that study domain.

The CSN daily HTML source remains disabled by default because it is a
research-only scraper without an operational service-level agreement. A manual
run requires `--allow-disabled-source`; that switch is an acknowledgement, not
a claim of source stability.

## Tectonic assets and grid

The commands below fetch the exact releases in `config/tectonic-assets.yaml` and
reject any byte-length or SHA-256 mismatch:

```bash
uv run chile-oef init-grid
uv run chile-oef ingest-chaf
uv run chile-oef ingest-slab2
uv run chile-oef classify-tectonics --limit 1000
```

The default grid covers 15–60°S and 62–82°W at 0.1°, totaling 90,000 cells. Grid
identity includes a deterministic definition hash. Static releases remain in
`building` state until all parsed records are committed; successful loads become
`ready`. Re-running a ready release reports its current record count rather than
duplicating rows.

CHAF attribution is required by CC-BY-4.0. Its typed dip/rake columns are only
convenience projections; original strings and interpretation status remain in
`properties_json`.

## Freeze a dataset

```bash
uv run chile-oef create-dataset \
  --dataset-id catalog \
  --version 2026-08-16 \
  --as-of 2026-08-16T23:59:59-04:00 \
  --git-commit "$GIT_COMMIT"
```

The selection contains one latest revision per native source event with
`available_at <= as_of`. Its manifest records revision IDs, artifact hashes,
source identities, cutoff, selection rule, and code commit. Creating the same
dataset ID/version twice is rejected.

## Verification

Unit and contract tests run without infrastructure:

```bash
uv run pytest -m "not integration"
```

Integration tests deliberately refuse any database whose name does not end in
`_test`:

```bash
docker compose exec -T db createdb -U chile_oef chile_oef_test
CHILE_OEF_TEST_DATABASE_URL=postgresql+psycopg://chile_oef:chile_oef@localhost:5432/chile_oef_test \
  uv run pytest -m integration
```

Final local gate:

```bash
uv run ruff check .
uv run ruff format --check .
uv run alembic check
CHILE_OEF_TEST_DATABASE_URL=postgresql+psycopg://chile_oef:chile_oef@localhost:5432/chile_oef_test \
  uv run pytest
```

## Operational observations

- Every retrieval creates an `ingestion_runs` record, including failed fetches.
- Identical content is stored once per source but linked to every retrieval run.
- Scientific source changes create append-only event revisions.
- Canonicalization retains all native observations and its match evidence.
- Historical reads and replay use `available_at`, never event origin time.
- The permanent disclaimer is returned with event catalog responses.

The smoke test on 2026-08-16 ingested two bounded USGS events. This is a
connectivity/provenance test only and is not scientific model validation.
