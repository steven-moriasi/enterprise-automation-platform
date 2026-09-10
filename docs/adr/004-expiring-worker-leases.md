# ADR 004: Recover abandoned work with expiring leases

- Status: accepted

## Context

An atomic queued-to-running claim prevents duplicate consumers from starting the same delivery, but a terminated worker can leave an execution permanently running.

## Decision

Store a worker owner, random fencing token, heartbeat, and expiry on each running execution. Renew the lease around every built-in step. The scheduler conditionally reaps expired tokens, requeues work while attempts remain, and dead-letters exhausted executions.

## Consequences

- Worker termination is recoverable without operator database edits.
- Conditional token checks prevent a stale worker from continuing through the normal state-transition path after reaping.
- The lease duration must exceed the expected non-interruptible step duration.
- External connectors still require provider-side idempotency because leases cannot undo remote side effects.
