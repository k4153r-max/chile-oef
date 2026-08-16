# ADR-0007: Uncalibrated tectonic residual baseline

Status: accepted, 2026-08-16.

## Decision

Phase 2 uses uncertainty mass derived from event depth relative to a pinned Slab2
surface as a transparent baseline. Every result records the event revision,
Slab2 release, optional CHAF release, method version, diagnostics and
`calibration_status=uncalibrated_rule_baseline`.

The baseline cannot be published as a calibrated class probability. CHAF distance
is diagnostic and does not modify its mass. Outer-rise and volcanic classes are
disabled. Results below the label threshold remain `unknown`.

## Rationale

A deterministic depth band discards meaningful hypocentral and slab uncertainty.
Conversely, a complex classifier trained without a defensible independent target
catalog would only turn expert assumptions into overconfident numbers. The chosen
baseline is inspectable, versionable and suitable for sensitivity analysis while
making the evidentiary gap explicit.

## Consequences

- Tectonic-conditioned rate models can use soft weights only while retaining the
  uncalibrated status.
- Promotion requires independent labels, out-of-sample calibration and robustness
  tests.
- A new Slab2/CHAF release or parameter set produces a new append-only result.
- Nearest surface-trace distance cannot be described as rupture-plane distance.
