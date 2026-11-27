# Session handoff

## Status

**System complete.** Core challenge (feat-001…007) + wishlist stretch (feat-008…012) are shipped. No active feature. Do not invent further scope unless the user asks.

## What is running

| Area | Behavior |
|------|----------|
| Submit | Office POST `/v1/prior-auths`; multi-field errors; optional `Idempotency-Key` |
| Support | `IntakeRejection` by `correlation_id` |
| Queue / claim | Atomic claim; COI 403; admin reassign |
| Decide | Whole-request; per-procedure outcomes; terminal + DB CHECK |
| Notify | Decide → outbox same txn → `outbox-worker` → MailDev |
| Workload | `GET /v1/reviewers/workload` (ops_admin) |
| Auditor | Read-only audit + list/get; mutations 403 |
| Member | `/me` strips clinical_note / denial_reason |
| Audit | Same DB transaction as every state change |

Plans (historical): `docs/plans/2026-11-24-prior-auth-api.md`, `docs/plans/2026-11-25-wishlist-outbox-maildev.md` (**shipped**).

## Agent ops (keep short)

- Prefer `README_FULL.md` Decisions + this handoff over re-reading full plans unless changing design.
- **Parallel work:** grit + `./scripts/grit_reindex.sh`; serialize Alembic. Skill: `.agent/skills/grit-parallel`.
- Never commit to `main` — branch + PR. Skills: `.agent/skills/open-pr`, `.agent/skills/stacked-prs`.
- Sync `origin/main` before starting work (rule: `.agent/rules/git-sync-before-work.mdc`).

## Walkthrough

1. State machine + matrices in `README_FULL.md` Decisions
2. `docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py`
3. `./scripts/demo.sh` — fail→support→submit→idempotency replay→claim 409→workload→COI→decide→MailDev→auditor→member redaction
4. OpenAPI: http://localhost:8000/docs · Grafana LGTM: http://localhost:3000

## Verify

```bash
./init.sh
./scripts/gates.sh
./scripts/demo.sh
```

## Blockers

None.

## Portfolio note

This tree is the **public** portfolio copy. Prefer defending product code (claim race, redaction, audit, outbox) over agent tooling when walking through the system.
