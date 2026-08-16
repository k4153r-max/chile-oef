# ADR-0005: Immutable forecasts

Status: accepted, 2026-08-16.

A forecast is an append-only scientific record. Corrections or recalculations
create a new forecast run linked through `supersedes_forecast_run_id`. Evaluation
results may be recomputed against newer truth catalogs without mutating forecasts.

