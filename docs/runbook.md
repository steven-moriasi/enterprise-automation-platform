# Operations runbook

## Readiness failure

1. Check `/health` to distinguish process liveness from dependency readiness.
2. Check PostgreSQL connectivity and migration status.
3. Check Redis connectivity.
4. Do not restart all services repeatedly; accepted executions may already exist in the outbox.

## Unpublished outbox growth

1. Confirm Redis is healthy.
2. Inspect scheduler logs for publish errors.
3. Restore broker connectivity.
4. The scheduler retries unpublished rows; do not manually duplicate queue messages.

## Retry backlog growth

1. Group failures by `last_error_code`.
2. Confirm whether the dependency is transient or the classification is wrong.
3. Compare retry delay and downstream recovery time.
4. Pause new triggers at the gateway if retry amplification threatens the dependency.

## Dead-letter recovery

1. Inspect the execution, failed step, failure records, and audit timeline.
2. Correct the workflow definition or dependency.
3. Use the retry endpoint only after the cause is addressed.
4. Verify the connector's idempotency behavior before replaying side effects.

## Worker termination during execution

1. Inspect the worker log and execution heartbeat.
2. Allow the lease to expire; the scheduler requeues it while attempts remain.
3. If attempts are exhausted, inspect the dead-letter record before manual retry.
4. Confirm whether an external side effect occurred because lease recovery does not replace connector idempotency.
