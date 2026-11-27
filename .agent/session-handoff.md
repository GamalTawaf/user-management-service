# Session handoff

## Status

**User Management API** on the public portfolio tree. Private Oxbridge take-home (`challenge/`) is separate and unchanged.

## What is running

| Area | Behavior |
|------|----------|
| Users | Admin create/list/get/patch; member `/me` |
| Lifecycle | invited → active → disabled (+ enable) |
| Orgs | create/list/get |
| Audit | Same DB transaction as state changes |
| Notify | create/status → outbox → MailDev |
| Idempotency | `Idempotency-Key` on `POST /v1/users` |
| Rate limit | Token bucket per client IP; Redis or in-process; `429` + headers |

## Verify

```bash
docker compose up -d
uv run alembic upgrade head
uv run python scripts/seed.py
./scripts/gates.sh
./scripts/demo.sh
```

## Portfolio note

Defend product code (lifecycle CHECKs, RBAC from DB, audit, outbox, idempotency, rate limit) over agent tooling.
