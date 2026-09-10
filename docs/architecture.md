# Architecture

## Boundaries

| Boundary | Responsibility | Does not own |
|---|---|---|
| API | validation, authorization, idempotent request acceptance | execution processing |
| PostgreSQL | workflow, execution, audit, retry, and outbox state | queue blocking/wakeup |
| Scheduler | publish outbox rows and make due retries deliverable | workflow step behavior |
| Redis | low-latency at-least-once delivery | authoritative execution status |
| Worker | claim executions and apply step policy | accepting client requests |
| Step runner | deterministic step behavior | persistence or retry policy |

## Consistency decisions

The API never writes directly to Redis as the only record of accepted work. The execution and dispatch intent are committed together. Publishing is asynchronous, so the API can return `202 Accepted` while delivery is pending.

Worker claims are conditional updates from `queued` to `running`. This prevents two deliveries from advancing the same execution concurrently. Each claim has an expiring fencing token that the worker renews around built-in steps. The scheduler conditionally requeues expired claims or dead-letters them after the workflow attempt limit.

Connector-level side effects require their own idempotency contract because a process can fail after the external system commits but before the local step result commits.

## Scaling path

1. Scale stateless API instances independently.
2. Add workers against the shared Redis queue; conditional claims prevent duplicate processing.
3. Partition only after measured contention exists, likely by tenant or workflow.
4. Move a module to a separate service only when it has an independent operational or data-ownership requirement.

The current design does not claim multi-region active/active behavior.
