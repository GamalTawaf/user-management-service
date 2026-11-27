# Wishlist stretch — workload, outbox→MailDev, auditor, Idempotency-Key

> **Status: SHIPPED** (feat-008…012). Historical plan — do not re-implement. Current system: README Decisions + `harness/session-handoff.md`.

**Goal (met):** Challenge wishlist plus deferred partner/compliance seams; decision notifications via transactional outbox → **MailDev**.

**Spec anchors**

- Challenge wishlist: notify office on decision; reviewer open-workload for team leads
- Challenge “auditors are next”
- Partners retry submits → `Idempotency-Key` (defendable one-liner: “partner POST timed out; retry must not double-create”)
- Prior cut list in README Decisions

**Non-goals**

- Real SES/SendGrid, GraphQL, event bus, AWS deploy, appeals, webhook fan-out
- Changing claim/decide race semantics
- Member/office UI

---

## Locked decisions

| Topic | Decision | Why |
|-------|----------|-----|
| Notify mechanism | Transactional **outbox** row in the **same DB txn** as decide + audit | Survive crash after commit; no silent “forgot to email” |
| Delivery target | **MailDev** in Compose (`SMTP 1025`, UI `1080`) | Visible inbox for demo; no real PHI egress |
| SMTP client | stdlib `smtplib` | No new prod dependency |
| Who gets mail | `practices.notification_email` (new column; seeded) | Practice has no email today; office user email is actor-specific |
| Worker | Compose service `outbox-worker` polling pending rows | Keeps API request path write-only; demo: decide → refresh MailDev |
| Workload | `GET /v1/reviewers/workload` — `ops_admin` only | Matches “team leads”; counts `status=in_review` grouped by `claimed_by_user_id` |
| Auditor | New `UserRole.auditor`; read-only `GET …/audit` (+ optional list requests read) | Challenge said auditors next; no mutations |
| Idempotency | Header `Idempotency-Key` on **`POST /v1/prior-auths` only** | Partner submit retry; claim/decide already conflict-safe |
| Idempotency scope | Unique `(practice_id, key)`; store request body hash + response snapshot | Same key + same body → replay `201`; same key + different body → `409` `idempotency_key_reuse` |
| Key TTL | 24h (document); prune optional later | Enough for partner retries |
| PR lanes | Split: workload (**medium**); outbox+MailDev (**medium**); auditor role (**high**); Idempotency-Key (**high**) | Avoid one mega-high PR |

---

## Architecture

```
decide() ──► UPDATE request + procedures
         ──► AuditEvent (existing)
         ──► OutboxEvent(kind=decision_notice, status=pending)   ← same transaction
                    │
                    ▼
         outbox-worker (poll) ── smtplib ──► MailDev:1025
                    │                         UI :1080
                    ▼
         status=sent | failed(+attempts)

POST /v1/prior-auths + Idempotency-Key
         ──► lookup (practice_id, key)
         ──► miss: submit as today; persist key + hash + PriorAuthOut JSON
         ──► hit + same hash: return stored 201 body
         ──► hit + different hash: 409
```

### New packages / files (keep thin)

```
app/outbox/
  models.py          # OutboxEvent
  mailer.py          # send_smtp(to, subject, body) via settings
  worker.py          # poll loop (module main)
  services.py        # enqueue_decision_notice, claim_batch, mark_sent/failed
app/workload/
  router.py          # GET /v1/reviewers/workload
  schemas.py
# OR put workload under prior_auth/router — prefer prior_auth if <40 lines
```

Auditor: extend `app/identity` + `app/audit/router` deps (`AdminOrAuditor`).  
Idempotency: `app/prior_auth/idempotency.py` + table; wire only in submit route/service.

### Settings (env)

```
SMTP_HOST=maildev          # empty/disabled in unit tests → mailer no-op or mock
SMTP_PORT=1025
SMTP_FROM=noreply@prior-auth.local
OUTBOX_POLL_SECONDS=2
OUTBOX_BATCH_SIZE=20
```

Tests: do **not** require MailDev. Mock `send_smtp` at the mailer function boundary for worker unit/HTTP-adjacent tests; one optional compose smoke in `demo.sh`.

### Compose additions

```yaml
maildev:
  image: maildev/maildev:2.1.0   # pin latest stable at implement time
  ports: ["1080:1080", "1025:1025"]

outbox-worker:
  build: .
  command: ["python", "-m", "app.outbox.worker"]
  environment:
    DATABASE_URL: …
    SMTP_HOST: maildev
    SMTP_PORT: 1025
  depends_on: [db, maildev]
```

API container does **not** send mail.

### Email content (minimal)

- **To:** `practice.notification_email`
- **Subject:** `Prior auth decision — {request_id}`
- **Body (text):** request id, member external id or member_id, DOS, per-procedure code → approved|denied (no clinical_note, no denial_reason text — office already can GET the request; keep email thin / HIPAA-aware)

### Outbox row shape

| Column | Notes |
|--------|--------|
| `id` | UUID PK |
| `kind` | `decision_notice` (string/enum; one kind for now) |
| `request_id` | FK nullable OK |
| `practice_id` | FK |
| `payload` | JSONB: `{to, subject, body}` or structured fields the worker renders |
| `status` | `pending` \| `sent` \| `failed` |
| `attempts` | int |
| `last_error` | text nullable |
| `created_at` / `sent_at` | timestamptz |
| Index | `(status, created_at)` for poll |

Worker: `SELECT … FOR UPDATE SKIP LOCKED` (or single-process poll for take-home simplicity — document single worker). Prefer SKIP LOCKED if easy.

### Idempotency table

| Column | Notes |
|--------|--------|
| `practice_id` + `key` | composite PK or unique |
| `request_hash` | sha256 of canonical JSON body |
| `response_status` | 201 |
| `response_body` | JSONB (`PriorAuthOut`) |
| `request_id` | UUID of created PA |
| `created_at` | for TTL story |

Missing header → current behavior (no idempotency). Empty key → 400 `idempotency_key_invalid`.

### Auditor visibility

| Capability | Auditor |
|------------|---------|
| `GET /v1/prior-auths/{id}/audit` | ✅ |
| `GET /v1/prior-auths` / `{id}` | ✅ read-all (optional but useful; include if cheap) |
| claim / decide / reassign / submit | ❌ 403 |
| member `/me` | ❌ |
| workload | ❌ (ops_admin only) |

Seed user `auditor@example.com` + token in seed output / Postman env.

---

## Execution note (historical)

Features were landed as separate PRs (workload → outbox → auditor → idempotency → docs) with linear Alembic heads. For future parallel agents: grit + `./scripts/grit_reindex.sh` (see `AGENTS.md`); still serialize Alembic.

---

## Feature breakdown (`harness/feature_list.json`) — all shipped

### feat-008 — Reviewer workload API (**medium**)

**Behavior:** `GET /v1/reviewers/workload` → list of `{ reviewer_id, display_name, open_count }` for reviewers with `open_count = COUNT(*)` where `status=in_review` AND `claimed_by_user_id = reviewer`. Include reviewers with 0? **No** — only those with ≥1 open, **plus** optionally all seeded reviewers with 0 for demo clarity. **Decision: return all users with `role=reviewer`, open_count default 0** (LEFT JOIN) so team leads see idle staff.

**Verify:** HTTP tests as admin 200; office/reviewer/member 403; after claim count increments; after decide decrements.

### feat-009 — Outbox + MailDev delivery (**medium**)

**Behavior:**

1. Migration: `practices.notification_email` NOT NULL (backfill seed); `outbox_events` table
2. `decide_request` enqueues outbox in same txn as audit
3. `app.outbox.worker` polls and SMTP-sends; marks sent/failed
4. Compose: `maildev` + `outbox-worker`
5. `demo.sh` step: decide → wait → assert MailDev API has message (MailDev HTTP API `GET /email`) **or** document manual UI check if API flaky
6. README: Decisions + how to open MailDev UI

**Verify:** unit/HTTP: decide creates pending outbox; worker with mocked SMTP marks sent; failure increments attempts. Compose smoke optional behind env flag.

### feat-010 — Auditor role (**high**)

**Behavior:** PG enum `auditor`; seed; `AdminOrAuditor` on audit GET; forbid mutations via existing role deps (no code path grants auditor write). OpenAPI/Postman token.

**Verify:** auditor can read audit; cannot claim/decide/submit/reassign (403); admin still works.

### feat-011 — Idempotency-Key on submit (**high**)

**Behavior:** as locked decisions; OpenAPI documents header; Postman example key.

**Verify:** two identical POSTs with same key → one row, same body; different body same key → 409; different keys → two rows; no header → two rows.

### feat-012 — README / demo / cut-list update (**low**)

Remove wishlist items from “Cut list”; document MailDev, workload, auditor, Idempotency-Key; extend `demo.sh` walkthrough; update session-handoff.

---

## Implementation order — complete

```
1. feat-008 workload          ✓
2. feat-009 outbox+MailDev    ✓
3. feat-010 auditor           ✓
4. feat-011 Idempotency-Key   ✓
5. feat-012 docs/demo         ✓
```

Postgres enum alter: use `ALTER TYPE … ADD VALUE` in a migration that does not run inside a transaction block if required (`alembic` `commit` pattern), or recreate enum — match existing project style.

---

## Defendability (45-min session)

| Question | Answer |
|----------|--------|
| Why outbox not `smtplib` in decide? | Decide must commit even if SMTP is down; outbox is the durability boundary |
| Why MailDev? | Take-home sink; swap SMTP_HOST for real relay later |
| Why only submit gets Idempotency-Key? | Partners create resources; claim/decide are naturally idempotent via state machine |
| Why auditor separate from admin? | Least privilege; auditors read trail, don’t reassign |

---

## Risks

| Risk | Mitigation |
|------|------------|
| Enum migration pain on `user_role` | Dedicated migration; test on fresh + upgrade-from-head |
| Worker double-send | SKIP LOCKED or single worker + status transition pending→sending→sent |
| Email leaks denial reasons | Body template omits clinical_note / denial_reason |
| Scope creep (webhooks, templates i18n) | Cut; one text template |
| Test flake on MailDev | Mock SMTP in pytest; MailDev only in demo/compose |

---

## Definition of done (epic)

- [x] All four behaviors live; cut list updated
- [x] `./scripts/gates.sh` green; compose includes MailDev + worker
- [x] `./scripts/demo.sh` shows decide → MailDev message
- [x] Evidence in `harness/feature_list.json` + `progress.md`
- [x] Split PRs by lane (workload / outbox / auditor / idempotency / docs)
