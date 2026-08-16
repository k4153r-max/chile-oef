# Data governance

## Temporal semantics

- `event_time`: physical origin time reported by a source.
- `source_updated_at`: source-side revision time, when provided.
- `received_at`: when CHILE-OEF obtained the payload.
- `available_at`: earliest defensible time a value could be used by a model.
- `recorded_at`: database transaction time.

`available_at` defaults to `received_at`, never to `event_time`.

## Provenance

Every raw artifact records URL, source, HTTP metadata, retrieval timestamp,
SHA-256, byte length, and media type. Parsed revisions record the parser version
and point back to the artifact; source-license metadata lives in the reviewed
source registry and its database projection.

Named dataset versions freeze the latest revision of every source event whose
`available_at` is not later than the declared `as_of`. The stored manifest lists
all selected revision IDs and content-addressed raw artifacts and is itself
identified by SHA-256. A different cutoff or selection requires a new version.

## Catalog truth

Input and evaluation catalogs are separate policies. Evaluation can be repeated
against a newer adjudicated catalog while the forecast and its input snapshot
remain unchanged. Results therefore record both forecast ID and observation
dataset version.

## Canonical events

Canonicalization groups source observations; it does not merge or overwrite raw
fields. Membership decisions are versioned and can be reversed. Preferred origin
and preferred magnitude policies are explicit and may select different products,
but each selected value retains lineage.
