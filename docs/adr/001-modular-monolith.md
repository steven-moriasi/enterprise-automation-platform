# ADR 001: Start with a modular monolith

- Status: Accepted
- Date: 2026-09-10

## Context

The platform needs distinct API, scheduling, execution, persistence, and identity responsibilities. Separate deployable services would add network contracts and operational failure modes before scale or team ownership requires them.

## Decision

Keep one Python codebase with explicit modules and three process entrypoints: API, scheduler, and worker. PostgreSQL remains the shared source of truth.

## Consequences

- Boundaries are reviewable without premature distributed transactions.
- Processes scale separately.
- Modules can be extracted later if measurements show contention or independent ownership.
- A shared database requires discipline around module ownership.
