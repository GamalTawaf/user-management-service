# Progress

## Shipped (2026-11-26)

All `.agent/feature_list.json` items **done** (feat-001…012).

| Slice | What’s in the tree |
|-------|--------------------|
| Core | Submit / intake support / claim race / COI / decide / reassign / member redaction / audit API |
| Tooling | Alembic, seed JWTs, Compose, multi-stage Docker, CI (lint/test/mutate/image), mutmut, `demo.sh`, Postman generator |
| Wishlist | Workload API, outbox→MailDev, auditor role, `Idempotency-Key` on submit, README/demo walkthrough |

**Verify:** `./init.sh` · `./scripts/gates.sh` · `./scripts/demo.sh`

**Handoff:** `.agent/session-handoff.md` (system complete — no next feature).

## Earlier session log (condensed)

- 2026-11-24 — MVP plan + feat-001…007; coding gates + PR lanes into AGENTS / Cursor rules
- 2026-11-25 — Wishlist plan + feat-008…012 implemented (workload → outbox → auditor → idempotency → docs)
