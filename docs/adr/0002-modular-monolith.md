# ADR-0002: Modular monolith

Status: accepted, 2026-08-16.

The initial system is a Python modular monolith with separate worker processes and
one PostgreSQL/PostGIS database. Kafka, Kubernetes, and distributed microservices
are deferred until measured operational requirements justify them.

