# ADR 003: Use a transactional dispatch outbox

- Status: Accepted
- Date: 2026-09-10

## Context

Writing an execution to PostgreSQL and publishing to Redis are two separate operations. A crash between them can lose accepted work or create a message without durable state.

## Decision

Commit the execution and an outbox row in one transaction. The scheduler publishes unpublished rows and records successful publication afterward.

## Consequences

- Accepted work is recoverable when Redis is unavailable.
- Publication is at least once, so duplicates are expected.
- Atomic execution claims and connector idempotency are required.
- Outbox retention and cleanup policy must be added before long-lived production use.
