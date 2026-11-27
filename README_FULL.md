# Prior Authorization API — full reference

Public portfolio copy of a prior-auth backend built for the [Oxbridge Health engineering challenge](https://github.com/rgavrilov5/prior-auth-api-challenge). Domain packages, one `/v1` surface, audit in the same transaction as state changes, role-scoped response schemas.

Synthetic seed data only. Demo JWT secret is intentional for local runs — never reuse in a real deployment (see Decisions).

Quick start and Postman walkthrough: [`README.md`](README.md).

## Who this is for

API roles are named for how people talk about the work:

| In the API / models | In plain language |
|---------------------|-------------------|
| **Members** | Our patients |
| **Provider offices** | Doctors' offices submitting requests for their patients |
| **Reviewers** | Our nurses and physicians who decide requests |
| **Operations admins** | The people who keep the work moving (reassign, workload) |
| **Auditors** | Read-only compliance viewers (audit trail; no mutations) |

Primary keys on models and in JSON are named **`uuid`** (not `id`) so the name matches the type. DB columns remain `id` for Postgres FKs.

## How to run

```bash
# Requires Python 3.15.x (Homebrew 3.15.2), Docker, uv
uv sync
docker compose up --build -d          # api entrypoint runs alembic upgrade head
uv run python scripts/seed.py         # prints JWT tokens (required once after empty DB)
curl -sf localhost:8000/v1/health
# pytest drops/recreates public schema on DATABASE_URL — re-seed (or restart api) after
uv run pytest -q --cov=app --cov-report=term-missing   # fail_under=100
./scripts/demo.sh
```

OpenAPI: [http://localhost:8000/docs](http://localhost:8000/docs)

Observability (Compose): Grafana LGTM at [http://localhost:3000](http://localhost:3000) — Tempo / Prometheus / Loki via OTLP (`api` + `outbox-worker` → `http://otel-lgtm:4318`). Explore Tempo for HTTP + SQL + `smtp.send` spans; Prometheus for `http.server.*` and `db.client.connections.usage`. No Redis. No login required for local LGTM.

## Seed tokens

`uv run python scripts/seed.py` prints Bearer JWTs for:

| Role key | Person |
|----------|--------|
| `office` | Provider office (seed practice: Riverside Clinic) |
| `reviewer` | Reviewer (nurse/physician) without COI on the seed member |
| `reviewer_coi` | Reviewer with a COI edge to the seed member |
| `admin` | Operations admin |
| `auditor` | Auditor (read-only) |
| `member` | Member (patient) portal |

Stable IDs (for curls): practice `11111111-…1111`, member `22222222-…2222`, unlinked `22222222-…2299`.

JWT secret must match the API (`JWT_SECRET`, default `dev-only-change-me-32bytes-min!!` in Compose).

## Decisions

### State machine

```
[intake validation]
   ├─ fail (domain OR schema/type) → IntakeRejection (durable; NOT in review queue)
   └─ ok  → PriorAuthRequest status=submitted, claimed_by=NULL
                │
                ▼ claim (atomic)
         status=in_review, claimed_by=<reviewer>, claimed_at=now
                │
                ├─ admin reassign → claimed_by=<other> (still in_review)
                └─ decide (all procedures in one shot)
                       status=decided, decided_by, decided_at
                       each procedure: approved | denied (+ reason if denied)
                       TERMINAL — no further mutations
```

**Invariants**

- Queue = `submitted` AND `claimed_by_user_id IS NULL`
- Claim: `UPDATE … WHERE id=:id AND status='submitted' AND claimed_by_user_id IS NULL`
- Decide = claim holder only (no admin override)
- `decided` ⇒ `decided_by_user_id NOT NULL` (DB CHECK `ck_decided_requires_actor`)
- Reviewer with COI edge to member cannot claim or decide
- Unlinked member → only `member_not_linked` (no coverage / other member-derived checks)
- Caps: ≤50 procedures/outcomes, clinical_note ≤10k chars, body ≤256 KiB (app + proxy)

### Audit matrix

| Action | Actor | Persist | Audit payload (min) |
|--------|-------|---------|---------------------|
| intake_reject | office | IntakeRejection + AuditEvent | correlation_id, fields[], practice_id |
| submit | office | request + procedures + AuditEvent | request_id, member_id, procedure codes |
| claim | reviewer | claim fields + AuditEvent | request_id, reviewer_id |
| reassign | ops_admin | claim fields + AuditEvent | request_id, from, to |
| decide | reviewer | procedure decisions + decided_* + AuditEvent | per-procedure outcomes |

Audit writes in the **same DB transaction** as the state change.

### Visibility matrix

| Field / capability | Member | Office (own practice) | Reviewer | Ops admin | Auditor |
|--------------------|--------|----------------------|----------|-----------|---------|
| List/get requests | own only | own practice | queue unclaimed + own claimed | all | all (read) |
| clinical_note | ❌ | ✅ | ✅ | ✅ | ✅ |
| denial_reason / reasoning | ❌ (approved \| not_approved only) | ✅ | ✅ | ✅ | ✅ |
| Audit trail | ❌ | — | ❌ | ✅ | ✅ |
| IntakeRejection lookup | ❌ | own practice by correlation_id | ❌ | all | ❌ |
| Workload | ❌ | ❌ | ❌ | ✅ | ❌ |
| Mutations (submit/claim/decide/reassign) | ❌ | submit only | claim/decide | reassign | ❌ |

### Glossary

- **PriorAuthRequest** — accepted submission that may enter the review queue
- **IntakeRejection** — durable failed submit; never in the queue
- **Claim** — exclusive assignment to one reviewer
- **COI** — reviewer treats that member; blocked from claim/decide
- **Final** — `decided`; appeals out of scope

### Clinical note — optional

Challenge: offices *can* attach a clinical note. We treat it as **optional** (`null` /
omitted). Requiring it would invent a UM rule they did not state. When present, max
10k chars (app + schema).

### Procedure / diagnosis codes — format only

CPT/HCPCS and ICD-10 are regex shape checks, not codebook membership. A well-formed but
unknown code passes intake; clinical validity is the reviewer’s job. Codebooks and
external validators are out of scope (cut list).

### Units > 30

Hard validation error with a “likely typo” message. Fail closed rather than soft-warn.
Enforced in the submit service only; the DB CHECK is `units >= 1`. The typo cap is
product policy at the API boundary, not a storage invariant (raw SQL could insert >30).

### Timezone / DOS window

DOS stored as `date`. “Today” and the one-year far bound use `America/New_York` via
`app/clock.py`. “More than a year out” = strictly after `today + 365` days (not a
calendar-year rollover).

### Support lookup — correlation_id only

Failed submits return `correlation_id` on the 422. Support looks up
`GET /v1/support/intake-rejections/{correlation_id}` (office: own practice; admin: all).
No free-text search by member / DOS / submitter — YAGNI for this take-home; the id is
the handoff from office → desk.

### Log PII / PHI masking

Root logger gets `PiiRedactingFilter` (`app/log_pii.py`) during telemetry setup (API +
worker). Redacts emails, JWTs / `Bearer` tokens, and values for `clinical_note`,
`denial_reason`, `member_id`, `authorization`, `password`, `ssn`, `dob` /
`date_of_birth`, `jwt_secret` in message text and log args.

OTel export wraps span exporters with `ScrubbingSpanExporter`: `db.statement` and
`db.query.text` run through the same field redaction plus SQL quoted-literal
masking (`'…'` → `'[REDACTED]'`) before Tempo/console see them. Other span
attributes and the audit table are unchanged. Member API redaction remains a
separate contract.

### JWT secret — accepted risk, not production-ready

`settings.jwt_secret` keeps a committed default (`dev-only-change-me-32bytes-min!!`) so the
take-home runs with one command and no secret handling. **This is a deliberate demo trade-off.**

The risk, stated plainly: that default is published here, in `docker-compose.yml`, and in
`scripts/demo.sh`, and `scripts/seed.py` pins `ADMIN_ID` to a fixed UUID. A deployment that
forgets to set `JWT_SECRET` therefore lets anyone who has read this repo mint a valid
`ops_admin` token and read every request, chart note, and audit event in the system. The
failure is silent — the app boots normally.

Before any real deployment: drop the default so `Settings` raises on a missing `JWT_SECRET`,
require ≥32 bytes from a secret manager, and rotate anything that ever ran with the demo value.

### Token lifetime

`mint_token` sets `exp` (24h default), and `get_current_user` decodes with
`options={"require": ["exp"]}`. A token without an expiry claim is rejected rather than
accepted forever, so every issued credential — including seed and demo tokens — ages out.

### Idempotency-Key (submit only)

Partners may send `Idempotency-Key` on `POST /v1/prior-auths`. Scope is `(practice_id, key)`.
Same key + same body replays the stored **201**; same key + different body → **409**
`idempotency_key_reuse`. Missing header = non-idempotent create. Keys are intended to live
**~24h** for partner retries; TTL prune is optional / YAGNI for this take-home.
Defendable one-liner: partner POST timed out; retry must not double-create. Claim/decide
are already conflict-safe via the state machine, so only submit takes the header.

### Reviewer workload

Challenge “team leads want open counts” → **ops_admin** (no separate lead role).
`GET /v1/reviewers/workload` returns every `role=reviewer` with `open_count` = count of
`status=in_review` claimed by that reviewer (LEFT JOIN, zeros included so idle staff
show up).

### Decision notify (outbox → MailDev)

`decide` writes an `outbox_events` row in the **same DB transaction** as the decision +
audit. Compose `outbox-worker` polls and SMTP-sends to **MailDev** (`SMTP 1025`, UI
[http://localhost:1080](http://localhost:1080)). To: `practices.notification_email`.
Subject names the member; body is a short office-facing note (member / DOS / request id /
procedure outcomes as Approved|Denied) — no `clinical_note` or `denial_reason` text. API
never opens SMTP.

```bash
docker compose up -d db maildev otel-lgtm api outbox-worker
# after decide: open MailDev UI, or GET http://localhost:1080/email
# traces/metrics/logs: http://localhost:3000 (Explore → Tempo / Prometheus / Loki)
```

### Auditor role

Seed user `auditor@example.com`. Read-only: `GET …/audit`, list/get all requests.
Mutations, `/me`, and workload → **403**. Least privilege vs ops_admin (admins still
reassign / read audit).

### Cut list (not built)

GraphQL, event bus, microservices, real IdP, appeals, retro review, CRUD UIs, AWS deploy,
real SES/SendGrid (MailDev only).

### Beyond the MVP cut list — shipped

Historical plan: [`docs/plans/2026-11-25-wishlist-outbox-maildev.md`](docs/plans/2026-11-25-wishlist-outbox-maildev.md).

| Capability | Behavior |
|------------|----------|
| Workload | `GET /v1/reviewers/workload` (ops_admin; all reviewers + `open_count`) |
| Decision notify | decide → transactional outbox → MailDev via `outbox-worker` |
| Auditor | read-only audit + list/get; mutations 403 |
| Idempotency | `Idempotency-Key` on `POST /v1/prior-auths` (~24h TTL story) |

### Coding standards

Domain packages, thin services, no restating comments. Audit/RBAC/validation and plan-required tooling (uv, OTel, multi-stage Docker, mutmut, CI) stay.

### Runtime versions

- Python **3.15.2** (Homebrew / `python:3.15.2-slim`)
- PostgreSQL **19** (`postgres:19`)
- **uv** only; prod deps in `[project].dependencies`, test/lint in `[dependency-groups] dev`

## Gates (commit + CI)

```bash
./scripts/gates.sh                 # ruff, call-style, fastapi compile, postman fresh, pytest
./scripts/install_git_hooks.sh     # pre-commit runs gates with GATES_SKIP_TESTS=1
```

- **ruff** — `ruff format --check` + `ruff check` (E/W/F/I/UP/B/SIM/C4/RUF)
- **call-style** — no nested non-constructor calls and no `if`/`and`/`or`/lambda expressions inside function call arguments (`scripts/check_call_style.py`; nested-call rule applies to `app/` except models/schemas)
- **fastapi compile** — `compileall` + `app.openapi()` + route callable inventory (`scripts/check_fastapi_compile.py`)
- **postman fresh** — committed `postman/Prior_Auth_API*.json` match a fresh generate (`scripts/check_postman_collection.py`)

Every CI step writes a pass/fail block to the GitHub Actions job summary.

## CI

GitHub Actions — thin `.github/workflows/ci.yml` calls reusable workflows:

1. **changes** — path filter (`code` vs meta-only)
2. **lint** — ruff + call-style + FastAPI/OpenAPI compile
3. **test** — Postgres 19 service, alembic, pytest with **100% coverage** gate
4. **mutate** — mutmut on `app/prior_auth/services` (see threshold below)
5. **image** — `docker build` only (no registry login/push)

Branch protection contexts are nested (`lint / lint`, …) because each job is a `workflow_call`.

Meta-only PRs (e.g. `.gitignore`, markdown, docs) still report those four checks green, but skip the heavy steps so branch protection is satisfied without mutmut/pytest/docker. Any change under `app/`, `tests/`, `scripts/`, `alembic/`, lockfiles, Docker, or `.github/workflows|actions` runs the full suite. Do not use `[skip ci]` — required checks would never report.

### Mutmut threshold

Scoped via `setup.cfg`: `source_paths=app/`, `only_mutate=app/prior_auth/services/*`.

**Do not run bare `uv run mutmut run`.** Use the wrapper — it prepares per-child DBs and sets the worker count:

1. **Parallel children** each claim an exclusive `prior_auth_mutmut_{i}` DB (via flock) so `DROP SCHEMA test_prior_auth` does not race. Default `--max-children 4` (`MUTMUT_MAX_CHILDREN`). Pytest still uses schema `test_prior_auth` only; app/dev data in `prior_auth` is never dropped.
2. **Stale `mutants/` cache** → `0 files mutated` and a spinner at `0.00 mutations/second` replaying old 🎉/🙁 counts. Wipe the cache (or use the wrapper).

```bash
./scripts/run_mutmut.sh
# more workers: MUTMUT_MAX_CHILDREN=8 ./scripts/run_mutmut.sh
# resumes only: MUTMUT_KEEP_CACHE=1 ./scripts/run_mutmut.sh
```

`setup.cfg` sets `on_dependency_change=rerun` so non-Python dep changes also invalidate results.

**Gate:** 0 not-checked; survivors ≤ `MUTMUT_MAX_SURVIVORS` (default 0 in CI and locally).

## Postman

Tracked (regenerate after OpenAPI / seed / JWT changes):

- [Collection](postman/Prior_Auth_API.postman_collection.json)
- [Environment](postman/Prior_Auth_API.postman_environment.json) (**Prior Auth Local**)

```bash
export JWT_SECRET=dev-only-change-me-32bytes-min!!   # must match Compose
./scripts/generate_postman_collection.py
# or: uv run python scripts/generate_postman_collection.py
```

Import both files in Postman (re-import after regenerating). Env JWTs use a fixed long-lived `exp` for stable generate/check; they still require `JWT_SECRET` to match Compose. Each request has a role token, demo body, and Tests scripts that write `request_id` / `procedure_id` / `correlation_id` from the response — Submit → Claim → Decide with no manual paste. Submit also refreshes `idempotency_key` on each Send. Pre-commit/CI byte-compares these files to a fresh generate.

Manual walkthrough (main README): [`README.md`](README.md).

## Live walkthrough

```bash
docker compose up -d   # db + api + maildev + outbox-worker
./scripts/demo.sh
```

Covers: failed submit → support → happy submit → **Idempotency-Key replay** → claim + 409
→ workload → COI 403 → decide → **MailDev check** → auditor audit GET → member redaction.

## How AI was used

- Planning: LLM council notes in `docs/council/` + written plans under `docs/plans/` (MVP then wishlist).
- Implementation: Cursor agents against those plans (TDD, surgical diffs). Humans kept Decisions, cut list, and race/audit/redaction invariants.
- Wrong turns fixed: uv only offered Python 3.15 beta → pin Homebrew/Docker **3.15.2**; install uv onto `python:3.15.2-slim` (no official uv image); mutmut 3 needs `source_paths=app/` with `only_mutate` on services.
- Tests are outside-in HTTP (except persistence-truth claim race + DB CHECK).

### Extras that AI made cheap to ship

Beyond the core prior-auth rules, this submission includes an **AI-oriented harness and production-shaped seams** that used to be “nice but expensive.” With agents, those steps are much less time-consuming, so the build can carry them for the value they add without eating the schedule:

- **Agent harness** — `AGENTS.md` / `CLAUDE.md`, shared `.agent/` (inventory, handoff, rules, skills; Cursor loads rules/skills via `.cursor/` symlinks)
- **CI/CD** — path-filtered required checks, lint/test/mutate/image as callable workflows, Postman freshness gate, branch protection as code
- **OpenTelemetry** — FastAPI + SQLAlchemy + logging + manual `smtp.send` spans; Compose → Grafana LGTM (Tempo / Prometheus / Loki)
- **Partner kit** — live OpenAPI, generated Postman collection/env, `README.md` walkthrough
- **Quality bar** — 100% coverage, mutmut on hot services, coding gates on every commit

The repo is also shaped so **AI agents can coordinate**: durable plans, risk-lane PR labels, gates that fail loudly, and docs that name the people in the system (not only role enums).

## Design notes

- Flat domain packages under `app/` (identity, master_data, prior_auth, intake, audit, outbox, shared)
- Thin routers; rules in `prior_auth/services/*`
- Role-specific response schemas (member strips note + denial reason)
- OpenTelemetry in `telemetry.py` (console default; Compose sets `OTEL_EXPORTER_OTLP_ENDPOINT` → `grafana/otel-lgtm` for traces, metrics, and logs). Instruments FastAPI (HTTP spans + server metrics), SQLAlchemy (DB spans + connection metrics), logging, and manual `smtp.send` spans in the outbox mailer. API + `outbox-worker` both export. No Redis in this stack.
