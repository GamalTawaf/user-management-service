# Progress

## Shipped (2026-11-27)

All `.agent/feature_list.json` items **done** (`ums-001`).

| Slice | What’s in the tree |
|-------|--------------------|
| Core | Orgs + users; admin/member/auditor RBAC; invited→active→disabled lifecycle; `/me`; audit-in-transaction; Idempotency-Key on create; stats |
| Tooling | Alembic, seed JWTs, Compose (db/redis/api/outbox/maildev/otel), multi-stage Docker, CI (lint/test/mutate/image), mutmut on `app/users/services`, `demo.sh`, Postman generator |
| Stretch | Outbox→MailDev, Redis token-bucket rate limiting + OTel, auditor role |

**Verify:** `./init.sh` · `./scripts/gates.sh` · `./scripts/demo.sh`

**Handoff:** `.agent/session-handoff.md` (system complete — no next feature unless new scope).

## Earlier session log (condensed)

- 2026-11-26 — UMS domain on the public portfolio tree
- 2026-11-27 — Rate limiting; Postman/CI naming cleanup
