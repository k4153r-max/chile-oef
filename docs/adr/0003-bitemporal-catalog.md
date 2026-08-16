# ADR-0003: Bitemporal catalog

Status: accepted, 2026-08-16.

Source revisions are append-only and preserve event, source-update, receipt,
availability, and transaction times. Current event state is a projection. This is
necessary for leakage-resistant replay and auditability.

