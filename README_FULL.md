# User Management API — full reference

Public portfolio service: organizations + user accounts with role-based access, lifecycle state machine, same-transaction audit, and outbox email.

Stack: FastAPI, Postgres, Alembic, JWT RBAC from DB (not token claims), ProblemBody errors, keyset pagination, Idempotency-Key, OTel + Grafana LGTM, mutmut on hot services, path-filtered CI.

Synthetic seed data only. Demo JWT secret is intentional for local runs — never reuse in production.

Quick start: [`README.md`](README.md).

## Decisions

### State machine

```
invited ──activate──► active ──disable──► disabled
                         ▲                   │
                         └──────enable───────┘
```

- Disabled users cannot authenticate (`403 Account disabled`).
- Invited users cannot authenticate until activated.
- Admins cannot disable themselves.
- `disabled` ⇒ `disabled_at IS NOT NULL` (DB CHECK).

### Roles

| Role | Capabilities |
|------|----------------|
| admin | CRUD users/orgs, lifecycle, stats, audit |
| member | `/me` and get self |
| auditor | read users/orgs/audit (no mutations) |

### Audit

Every create / update / activate / disable / enable / org_create writes `audit_events` in the **same transaction**.

### Outbox

`user_welcome` on create; `user_status` on activate/disable/enable. Worker polls with `SKIP LOCKED` → MailDev. Transient send errors leave the row `pending` and increment `attempts` until `OUTBOX_MAX_ATTEMPTS` (default 5), then `failed`.

### Idempotency

`Idempotency-Key` on `POST /v1/users` only; scoped per admin. Same key + body → replay 201; different body → 409.

### Rate limiting

Token-bucket limiter runs as ASGI middleware (before auth):

- Key: client IP (`X-Forwarded-For` first hop, else peer host). **Caveat:** any client can spoof `X-Forwarded-For` unless a trusted reverse proxy strips/overwrites it. Treat the key as advisory for local demos; put a proxy in front before relying on per-IP fairness in production.
- Backend: Redis when `REDIS_URL` is set (hash get/set); otherwise in-process memory (tests / local without Redis). **Caveat:** the in-process store is per-process — multi-worker / multi-replica deploys need Redis for a shared bucket.
- Defaults: capacity `120`, refill `2` tokens/sec (`RATE_LIMIT_CAPACITY`, `RATE_LIMIT_REFILL_PER_SECOND`)
- Exempt: `/v1/health`, OpenAPI docs paths
- Responses: `X-RateLimit-Limit` / `X-RateLimit-Remaining`; on reject `429` ProblemBody (`rate_limited`) + `Retry-After`
- Telemetry: `ums.rate_limit.allowed` / `ums.rate_limit.rejected` counters, `rate_limit.consume` spans, Redis client instrumentation; stdlib/uvicorn logs via OTLP → Loki when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (`LOG_LEVEL`, default `INFO`)

### Orgs

Organizations are first-class tenants (`POST/GET /v1/orgs`). Users may optionally belong to one org (`org_id`); auditors can read orgs, admins mutate.

### Cut list

No real IdP / SSO, password reset / MFA, GraphQL, microservices, AWS deploy, SES. Local login uses bcrypt hashes (`POST /v1/auth/login`). `.env.example` documents knobs; Compose injects its own env.

## How to run

See [`README.md`](README.md). Compose services: `db`, `redis`, `api`, `outbox-worker`, `maildev`, `otel-lgtm`.

## Gates / CI

```bash
./scripts/gates.sh
```

ruff · call-style · FastAPI compile · Postman fresh · pytest 100% coverage. Mutmut: `./scripts/run_mutmut.sh` (`app/users/service.py`).

## AI usage

Planning/implementation assisted by Cursor agents; humans owned the domain decisions (user/org lifecycle, RBAC matrix, audit/outbox seams). Tests are outside-in HTTP.
