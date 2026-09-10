# Principal Engineer review

Review date: 2026-09-10

## Scope

The review covered the API contract, execution state machine, database consistency, Redis delivery semantics, worker recovery, authentication boundary, webhook trust boundary, migrations, tests, containers, CI, and operational documentation.

## First-pass findings and remediation

| Severity | Finding | Resolution |
|---|---|---|
| Critical | A terminated worker could leave an execution permanently running | Added expiring leases, heartbeats, fencing tokens, bounded reaping, migration coverage, tests, ADR 004, and runbook steps |
| High | The manual trigger accepted a client-supplied trigger classification | The route now assigns `manual`; input models reject unknown fields |
| High | Webhook signature processing and synchronous database work shared an async route | Raw-body reading is an async dependency; the database route runs in FastAPI's worker thread |
| Medium | Manual retry audit metadata recorded the reset attempt count | Capture and audit the prior attempt count before resetting the budget |
| Medium | Redis client failures were not explicitly covered by readiness exception handling | Readiness now catches Redis client errors |
| Medium | CI actions used mutable major-version tags | Actions are pinned to resolved commit SHAs and Dependabot tracks updates |
| Medium | Worker-termination runbook guidance contradicted the lease implementation | Updated the runbook to describe automatic recovery and connector-side checks |

## Verification

- Ruff passed across application, tests, and migrations.
- Strict mypy passed across the application.
- The 28-test suite passed.
- PostgreSQL migrations passed upgrade, downgrade-to-base, and re-upgrade.
- Docker Compose built and started PostgreSQL, Redis, migration, API, scheduler, and worker services.
- Container smoke verification completed manual, signed-webhook, and scheduled executions through the worker.

## Residual risks

- External connector adapters and their provider-side idempotency contracts are intentionally outside this release.
- The test suite uses SQLite for service and API isolation; CI verifies PostgreSQL migrations but not the full execution suite against PostgreSQL.
- OIDC validation is implemented, but an end-to-end Keycloak realm test is still roadmap work.
- Metrics and structured logs exist; distributed trace export is not implemented.
- Fixed-interval scheduling does not provide cron expressions, calendars, or misfire policies.
- The reference system has not been load tested and makes no production throughput or availability claim.

## Second-pass verdict

No unresolved critical finding remains in the stated reference-implementation scope. The repository is suitable as Phase 1 portfolio evidence because it demonstrates explicit consistency, recovery, security, audit, migration, testing, and operational decisions without presenting roadmap capabilities as complete.
