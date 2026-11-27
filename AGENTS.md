# AGENTS.md

User Management API (public portfolio). Durable Python + PostgreSQL backend showcasing JWT/RBAC, audit, outbox, idempotency, and CI gates — without prior-auth domain code.

## Status

**UMS domain rewrite complete** on this public tree. Private `challenge/` take-home is separate and unchanged.

## Startup

1. `pwd` → this repo root (`prior-auth-api` folder / `user-management-api` package)
2. Read this file + `README_FULL.md` Decisions when touching domain behavior
3. `docker compose up -d && uv sync && uv run alembic upgrade head && uv run python scripts/seed.py`
4. `./scripts/gates.sh` before claiming done

## Coding gates

Mirrored in `.agent/rules/coding-gates.mdc`. Prefer `tests/conftest.py` helpers; extract shared utils at 2+ call sites; no nested call/condition style violations.

## Layout

```
app/
  identity/   # User, roles, JWT, RBAC
  orgs/       # Organization tenant
  users/      # CRUD + lifecycle services/router
  audit/      # AuditEvent + writer
  outbox/     # welcome/status email worker
  shared/     # errors, deps, middleware
```

## Verification

```bash
./scripts/gates.sh
./scripts/demo.sh
```
