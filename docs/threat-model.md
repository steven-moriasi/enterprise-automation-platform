# Threat model

## Assets

- workflow definitions;
- execution input/output;
- identity and role claims;
- audit records;
- integration secret references;
- availability of API and worker capacity.

## Trust boundaries

- untrusted API clients to FastAPI;
- OIDC issuer to token-validation adapter;
- API/scheduler/worker to PostgreSQL and Redis;
- future connector adapters to third-party systems.

## Primary threats and controls

| Threat | Control |
|---|---|
| Forged identity | Verify JWT signature, issuer, audience, and expiry via issuer JWKS |
| Role escalation | Server-side role checks; never trust a client-provided role when auth is enabled |
| Replay/duplicate triggers | Workflow-scoped idempotency key |
| Secret disclosure in definitions | Reject common secret-like configuration keys; use managed references |
| Arbitrary code execution | Fixed step registry; no user code or shell execution |
| SSRF through workflow configuration | No arbitrary HTTP step in the core engine |
| Audit tampering | Append-only API behavior; database privilege separation remains deployment work |
| Sensitive logs | Structured event fields and no payload logging by default |
| Queue message forgery | Queue contains identifiers only; worker reloads authoritative state |
| Denial of service | Input size/step-count bounds; deployment rate limits remain required |

## Development authentication warning

`X-Dev-Subject` and `X-Dev-Roles` exist only when authentication is disabled. A production deployment must enable OIDC and prevent direct access to an instance configured for development authentication.
