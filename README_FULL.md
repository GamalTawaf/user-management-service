# User Management API — full reference

Public portfolio service: organizations + user accounts with role-based access, lifecycle state machine, same-transaction audit, and outbox email.

Challenge-inspired foundation (not the prior-auth product): FastAPI, Postgres, Alembic, JWT RBAC from DB (not token claims), ProblemBody errors, keyset pagination, Idempotency-Key, OTel + Grafana LGTM, mutmut on hot services, path-filtered CI.

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

`user_welcome` on create; `user_status` on activate/disable/enable. Worker polls with `SKIP LOCKED` → MailDev.

### Idempotency

`Idempotency-Key` on `POST /v1/users` only; scoped per admin. Same key + body → replay 201; different body → 409.

### Cut list

No real IdP, password reset flows, GraphQL, microservices, AWS deploy, SES.

## How to run

See [`README.md`](README.md). Compose services: `db`, `api`, `outbox-worker`, `maildev`, `otel-lgtm`.

## Gates / CI

```bash
./scripts/gates.sh
```

ruff · call-style · FastAPI compile · Postman fresh · pytest 100% coverage. Mutmut: `./scripts/run_mutmut.sh` (services under `app/users/services`).

## AI usage

Planning/implementation assisted by Cursor agents; humans owned the domain rewrite (user/org lifecycle, RBAC matrix, audit/outbox seams). Tests are outside-in HTTP.
