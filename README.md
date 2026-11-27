# User Management API

Portfolio project: a durable Python + PostgreSQL **user management** service with JWT/RBAC, audit-in-transaction, outbox→MailDev, idempotency, OTel, and 100% coverage gates.

For full info (Decisions, CI, AI usage), use [`README_FULL.md`](README_FULL.md).

## 1. Start the stack

```bash
docker compose up --build -d
export JWT_SECRET=dev-only-change-me-32bytes-min!!
export DATABASE_URL=postgresql+psycopg://ums:ums@localhost:5432/user_mgmt
uv sync
uv run alembic upgrade head   # also runs on API container start
uv run python scripts/seed.py
```

API: http://localhost:8000/docs  
Health: http://localhost:8000/v1/health

## 2. What you get

| Area | Behavior |
|------|----------|
| Users | create / list / get / patch; roles `admin` \| `member` \| `auditor` |
| Lifecycle | `invited` → `active` → `disabled` (DB CHECK on disable timestamp) |
| Self | `GET/PATCH /v1/me` |
| Orgs | create / list / get |
| Audit | same DB transaction as state changes |
| Notify | create/status → transactional outbox → MailDev |
| Idempotency | `Idempotency-Key` on `POST /v1/users` |
| Rate limit | token bucket per client IP; Redis (`REDIS_URL`) or in-process; OTel counters/spans; `429` + `Retry-After` / `X-RateLimit-*` |

## 3. Postman

```bash
export JWT_SECRET=dev-only-change-me-32bytes-min!!
./scripts/generate_postman_collection.py
```

Import `postman/User_Management_API*.json` after regenerating.

## 4. Demo

```bash
docker compose up -d
./scripts/demo.sh
```

| What | URL |
|------|-----|
| MailDev | http://localhost:1080 |
| Grafana LGTM | http://localhost:3000 |
