# Data-source register

The machine-readable authority is `config/source-registry.yaml`. This document
summarizes the Phase 1 acquisition policy.

## CSN

The Centro Sismologico Nacional is the preferred national authority. Its daily
catalog pages and published catalog snapshots are real sources, but no stable,
documented public event API was verified at project inception. The nominal FDSN
event service must not be treated as usable until a probe returns catalog data and
the interface is confirmed with CSN.

CSN HTML ingestion is cache-aware, low-frequency, and schema-monitored. It is a
research adapter, not an assumed service-level agreement. Academic and outreach
reuse must attribute the full CSN name; other uses require written approval under
the published usage terms.

## USGS

GeoJSON summary feeds provide low latency. FDSN Event/ComCat provides historical
and revision reconciliation. Queries are partitioned to remain below the 20,000
result limit. Detail products are archived because preferred origins, magnitudes,
focal mechanisms, and tensors can change.

## EarthScope

EarthScope is used for stations, waveforms, and later GNSS where Chilean coverage
exists. Current `service.earthscope.org` endpoints are configurable; legacy IRIS
hostnames are not embedded in model code. Continuous near-real-time waveform
access uses streaming services rather than polling dataselect.

## Static tectonic data

Slab2, CHAF, and the South American Moho model are pinned by release, checksum,
and license. They never update silently.

## Redistribution

The source-code license does not cover external data. Raw data are excluded from
Git. Public deployments require a source-by-source legal review.

