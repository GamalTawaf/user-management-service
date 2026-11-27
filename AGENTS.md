# AGENTS.md

User Management API (public portfolio). Durable Python + PostgreSQL backend showcasing JWT/RBAC, audit, outbox, idempotency, rate limiting, and CI gates.

## Status

**UMS domain complete** on this tree.

## Startup

1. `pwd` → this repo root (`user-management-service` / `user-management-api` package)
2. Read this file + `README_FULL.md` Decisions when touching domain behavior
3. `docker compose up -d && uv sync && uv run alembic upgrade head && uv run python scripts/seed.py`
4. `./scripts/gates.sh` before claiming done

## Coding gates

Mirrored in `.agent/rules/coding-gates.mdc`. Prefer `tests/conftest.py` helpers; extract shared utils at 2+ call sites; no nested call/condition style violations. One `service.py` per domain (no `services/` packages).

## Layout

```
app/
  identity/    # User, roles, JWT, RBAC
  orgs/        # Organization tenant
  users/       # service.py + router (+ schemas/idempotency)
  audit/       # models + service.write_audit
  outbox/      # service.py + worker + mailer
  rate_limit/  # token-bucket middleware (Redis or in-process)
  shared/      # errors, deps, middleware
```

## Verification

```bash
./scripts/gates.sh
./scripts/demo.sh
```
