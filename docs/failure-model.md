# Failure model

| Failure | Expected behavior | Evidence |
|---|---|---|
| Duplicate client trigger | Unique workflow/idempotency key returns original execution | API test |
| Duplicate signed webhook | Provider event ID returns the original execution | API test |
| Invalid webhook signature | Reject before workflow lookup or execution creation | API test |
| API commits but Redis is unavailable | Unpublished outbox row remains durable | scheduler test |
| Scheduler publishes then crashes | Message may be duplicated | atomic worker claim test |
| Duplicate queue delivery | Only one delivery changes `queued` to `running` | execution service test |
| Two schedulers observe one due interval | Conditional due-time update creates one execution | scheduling test |
| Transient step failure | Retry scheduled with bounded backoff and jitter | retry test |
| Permanent step failure | Immediate dead-letter state | failure test |
| Repeated transient failure | Dead-letter after maximum attempts | exhaustion test |
| Worker crashes while `running` | Scheduler requeues an expired lease or dead-letters after the attempt limit | lease-reaper test |
| Database unavailable | Readiness fails; work is not acknowledged locally | readiness behavior |
| Redis unavailable | Readiness fails; outbox record remains unpublished | scheduler behavior |
| External side effect succeeds before local commit | Connector must supply idempotency/inbox evidence | adapter contract |

## Worker lease boundary

Each claim receives a random fencing token and bounded expiry. The worker renews the lease before and after each built-in step. If the lease has been reaped, the stale worker cannot persist another step transition through the normal execution path.

Connectors that perform external side effects must still supply an idempotency key because no database lease can roll back an already accepted third-party request.
