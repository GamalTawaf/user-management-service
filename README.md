# Prior Authorization API

Portfolio project: a durable Python + PostgreSQL prior-authorization backend (submit → claim → decide, audit, RBAC, outbox notify). Built against the public [Oxbridge Health prior-auth challenge](https://github.com/rgavrilov5/prior-auth-api-challenge).

Quick start and manual Postman walkthrough below.

For full info (Decisions, CI, AI usage, observability, cut list), use [`README_FULL.md`](README_FULL.md).

## 1. Start the stack

```bash
docker compose up --build -d
# wait until healthy, then:
export JWT_SECRET=dev-only-change-me-32bytes-min!!
export DATABASE_URL=postgresql+psycopg://prior:prior@localhost:5432/prior_auth
uv run python scripts/seed.py
```

API: http://localhost:8000/docs  
Health: http://localhost:8000/v1/health

## 2. Generate + import Postman

Latest generated files in the repo (also safe to regenerate):

- [postman/Prior_Auth_API.postman_collection.json](postman/Prior_Auth_API.postman_collection.json)
- [postman/Prior_Auth_API.postman_environment.json](postman/Prior_Auth_API.postman_environment.json)

```bash
export JWT_SECRET=dev-only-change-me-32bytes-min!!   # must match Compose
./scripts/generate_postman_collection.py
```

In Postman: **Import** those two files → select env **Prior Auth Local**. After regenerating, **re-import** (or replace) so bodies, Tests scripts, and tokens stay in sync. CI/pre-commit fails if committed JSON ≠ a fresh generate.

Tests scripts auto-set `request_id`, `procedure_id`, and `correlation_id` from responses. Submit refreshes `idempotency_key` each Send.

## 3. Postman cases

Use the role token already set on each request (or switch env `token`).

### A. Intake rejection → support lookup

1. **Submit Prior Auth** — set body `member_id` to `{{member_unlinked_id}}` → Send → expect **422**.
2. Env `correlation_id` should update from the response.
3. **GET support intake-rejection** → Send → expect **200** with `field_errors`.

### B. Happy path (submit → claim → decide → email)

1. **Submit Prior Auth** — body uses `{{member_id}}` (default) → **201**.
2. **Claim** → **200** (`in_review`).
3. **Decide** — body already has `{{procedure_id}}` / `approved` → **200**.
4. Check MailDev for the decision notice (see URLs below).

### C. Claim race / COI

1. After a successful Claim, **Claim** again → **409**.
2. Submit a new PA (step B.1), then Claim with auth `{{reviewer_coi_token}}` → **403**.

### D. Member portal

1. After a decided (or submitted) PA, **GET me/prior-auths** (member token) → list without clinical note.
2. **GET me/prior-auth by id** using `{{request_id}}`.

### E. Ops extras

1. **GET reviewers/workload** (admin) after some claims.
2. **GET audit** (auditor token) for `{{request_id}}`.
3. Submit twice with the same `Idempotency-Key` header → same prior-auth `id`.

## 4. Emails + logs / traces

| What | URL |
|------|-----|
| MailDev inbox (decision emails) | http://localhost:1080 |
| MailDev JSON API | http://localhost:1080/email |
| Grafana LGTM (no login) | http://localhost:3000 |
| Loki logs | Grafana → **Explore** → datasource **Loki** |
| Traces (HTTP / SQL / `smtp.send`) | Grafana → **Explore** → **Tempo** |
| Metrics | Grafana → **Explore** → **Prometheus** |

Compose ships `api` + `outbox-worker` OTLP to `otel-lgtm`. Decision emails only appear after Decide, once the outbox worker has polled (a few seconds).
