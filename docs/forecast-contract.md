# Forecast contract

Every forecast definition is registered before it is evaluated.

## Required dimensions

- issue schedule and trigger type;
- UTC issue, validity start, and validity end;
- grid version, cell, depth range, and optional tectonic class;
- non-overlapping magnitude bins and source magnitude policy;
- input catalog snapshot and its `as_of` time;
- target/evaluation catalog policy;
- model and parameter-set version;
- completeness policy;
- probability, rate, expected count, and uncertainty method;
- estimability and data-quality state.

## Coherence constraints

For exceedance probability, magnitude thresholds must be non-increasing and
horizons non-decreasing. CHILE-OEF stores rates in non-overlapping magnitude bins
and derives exceedance products where possible.

## Availability invariant

An input record participates only when its recorded `available_at` is no later
than `issued_at`. A final catalog produced later can be used as evaluation truth,
but cannot be substituted into the historical input snapshot.

## Immutability

Published forecast rows cannot be updated or deleted through the application
role. A recalculation creates a new run with `supersedes_forecast_run_id`.

## Not estimable

A probability is not issued if any mandatory condition fails, including:

- target threshold below Mc;
- stale or unavailable source beyond the registered tolerance;
- insufficient spatial/temporal support;
- invalid model state;
- incoherent probability output.

The API returns a reason code rather than zero probability.

