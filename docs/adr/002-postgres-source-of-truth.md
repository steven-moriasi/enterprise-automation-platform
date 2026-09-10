# ADR 002: PostgreSQL owns execution state

- Status: Accepted
- Date: 2026-09-10

## Context

Redis is useful for waking workers but queue-only state makes audit, retry, and operator recovery difficult.

## Decision

Persist workflow, execution, step, retry, failure, audit, and dispatch intent in PostgreSQL. Redis messages contain only execution identifiers.

## Consequences

- Operators can reconstruct decisions from durable state.
- Duplicate messages are safe when claims are conditional.
- Database availability is required to accept or process work.
- High-volume deployments must measure database contention before partitioning.
