# Prior Authorization API — Implementation Plan

> **Status: SHIPPED** (feat-001…007 core; wishlist feat-008…012 also shipped — see `2026-11-25-wishlist-outbox-maildev.md`). Historical plan. Current system: README Decisions + `harness/session-handoff.md`.

**Goal (met):** Durable Python + PostgreSQL prior-auth backend a teammate would inherit, defendable line-by-line in a 45-minute live walkthrough.

**Architecture:** Single FastAPI app with **domain packages** (`identity`, `master_data`, `prior_auth`, `intake`, `audit`, `outbox`, `shared`) and one resource-oriented `/v1` surface. Rules live in domain services; audit in the same DB transaction as state changes; role-specific response schemas enforce redaction. Observability via OpenTelemetry. Tooling: `uv` (prod/dev split), multi-stage Docker, CI (build no push) + pytest + mutmut.

**Tech Stack:** Python **3.15** + PostgreSQL **19** + **latest stable** library releases (see Version policy). FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, PyJWT, OpenTelemetry, `uv`, multi-stage Docker, Compose, pytest+httpx, mutmut, GitHub Actions.

**Spec:** Challenge README — https://github.com/rgavrilov5/prior-auth-api-challenge  
**Council input:** `council-transcript-20261124-230109.md` (reorder around state/audit/visibility; cut wishlist padding)  
**Operating skills (mandatory for implementers):**
- [Ponytail](https://github.com/DietrichGebert/ponytail/blob/main/skills/ponytail/SKILL.md) — **full** (session-default until “stop ponytail”)
- [Karpathy guidelines](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md) — think / simplicity / surgical / goal-driven

Copy Karpathy rules into project as `CLAUDE.md` (and optionally `.cursor/rules/karpathy-guidelines.mdc`) in Task 1 so every worker loads them.

---

## Agent operating mode

### Ponytail (full)

Stop at the first rung that holds: YAGNI → stdlib/platform → installed dep → one clear line → minimum code.

- No unrequested abstractions, factories, “for later” scaffolding, or config for values that never change.
- Fewest files that stay readable; shortest working diff; deletion over addition; boring over clever.
- Never cut: trust-boundary validation, audit integrity, security/RBAC, data-loss prevention, anything this plan explicitly requires (OTel, mutmut, multi-stage Docker, CI, IntakeRejection, etc.).
- Deliberate shortcuts with a known ceiling: one-line `# ponytail: <limit>, <upgrade when>` — only when the limit is not obvious from names.
- Non-trivial logic leaves one failing-then-passing check (pytest); no per-function test theater.

### Karpathy guidelines

1. **Think before coding** — state assumptions; surface tradeoffs; ask when unclear; don’t silently pick an interpretation.
2. **Simplicity first** — no speculative features/abstractions/config; if 200 lines could be 50, rewrite.
3. **Surgical changes** — touch only what the task needs; clean up only orphans *you* created; don’t “improve” adjacent code.
4. **Goal-driven execution** — every step has `→ verify:`; loop until the check passes. Prefer red→green over “make it work.”

### Code clarity (no noise comments)

- Prefer names, types, and structure that a stranger can read without narration.
- **No comments** that restate what the code already says.
- Comment **only** when the *why* is invisible from the code (invariant, non-obvious constraint, intentional shortcut). One line max.
- Docstrings: public API modules / OpenAPI-facing behavior only when the signature is not enough — not on every function.
- Follow normal Python best practices: PEP 8 via formatter (`ruff` format/check), explicit types on public functions, narrow exceptions at boundaries, no bare `except`, no mutable defaults, dependencies pinned in `uv.lock`.

### Tension resolution (when skills disagree)

| Conflict | Resolve as |
|----------|------------|
| Ponytail “fewest files” vs domain folders | **User-requested domain packages win.** Keep each domain thin (models/schemas/services/router co-located); no extra layers (`repos/`, factories). |
| Ponytail skip vs plan-required tooling | Plan wins for uv / OTel / multi-stage / mutmut / CI / IntakeRejection / DB CHECKs. |
| Karpathy “ask when unclear” vs ponytail “default and ship” | Ambiguity that changes compliance/audit/visibility → **ask**. Ambiguity that is pure style → **default boring and note in README Decisions**. |

---

## Global Constraints

- Start **locally** — no remote repo required to begin; init git locally; private GitHub template copy only when ready to submit / add `rgavrilov5`.
- Python **3.15.x** (latest stable major; `.python-version` = `3.15`). Prefer Homebrew/Docker **3.15.2** (or newer 3.15.x) over a uv-managed beta if `uv python list` only offers prereleases. Package manager **`uv`** only.
- PostgreSQL **19** in Compose/CI (`postgres:19`).
- All deps: **latest stable** at scaffold; no alphas/RCs except OTel instrumentations’ upstream `0.xbY` line paired with API/SDK 1.x (see Version policy). Lock in `uv.lock`.
- **Split prod vs dev in uv:** runtime packages in `[project].dependencies`; test/lint/mutation in `[dependency-groups] dev`. Add with `uv add …` vs `uv add --dev …`. Local/CI: `uv sync` (includes dev). Docker prod image: `uv sync --frozen --no-dev` (or `--no-group dev`). Never put pytest/ruff/mutmut/httpx2 (test client) in prod deps.
- Logging + metrics via **OpenTelemetry** (OTLP-exportable; console/exporter stub OK locally). Keep `telemetry.py` thin.
- Docker: **multi-stage** on `python:3.15.2-slim` (or newer 3.15.x-slim); Compose = API + `postgres:19`.
- CI: GitHub Actions builds image (**no registry push**) and runs tests (pytest + mutmut).
- Synthetic data only; no real PHI.
- MVP cut list deferred items are **shipped** in the wishlist stretch (`docs/plans/2026-11-25-wishlist-outbox-maildev.md`: outbox→MailDev, workload, auditor, Idempotency-Key).
- Still out of scope: GraphQL, event bus, microservices split, real IdP, appeals, retro review, CRUD UIs, AWS deploy, real SES/SendGrid.
- Timezone: DOS stored as `date`; “today” evaluated in **`America/New_York`** (`clock.py`).
- Units > 30 → **hard validation error** (document: “almost always a typo”).
- Member responses never include clinical note or denial/reviewer reasoning.
- DB must enforce: `status = decided` ⇒ `decided_by_user_id IS NOT NULL`; claim is atomic `UPDATE … WHERE claimed_by_user_id IS NULL`.
- Implement under **ponytail full + Karpathy** rules above; no narrative comments.
- **Tests = user flow:** drive behavior through real HTTP API calls; mock only DB responses and/or external calls — never mock app internals (see Testing strategy).

## Review Focus

1. Concurrent claim race — exactly one reviewer wins; other gets conflict.
2. Decided request mutated again — 409/422; no reassign/redecide.
3. Member GET of denied request — no note, no denial reason text.
4. Support lookup of failed intake by correlation id — durable row, not only 422 body.
5. Approve path without actor — impossible (DB CHECK + service audit in same transaction).

---

## Council deltas from prior draft (locked)

| Prior draft | Now |
|-------------|-----|
| Phases 0–6 + repo URL blocker | Local-first; **3 vertical slices** after matrices page |
| Router packages per actor | One API package + RBAC deps; role-specific **response schemas** |
| Outbox stub + optional Idempotency-Key | **Cut** from MVP |
| Status enum alone | Status **plus** `claimed_by` / `claimed_at` / `decided_by` / `decided_at` + procedure-level decisions |
| Intake = 422 only | Persist **`IntakeRejection`** (correlation id, payload, field errors, actor, at) |
| poetry / unspecified | **`uv`** |
| Python 3.12+ / unpinned deps | **Python 3.15** + **Postgres 19** + latest stable PyPI (Version policy) |
| Structured logging only | **OpenTelemetry** logs + metrics |
| Single-stage Docker | **Multi-stage** on `python:3.15-slim` |
| pytest only | pytest **+ mutmut** |
| No CI | **GitHub Actions**: build image (no push) + test |
| Layered package sprawl | **Domain packages** (identity, master_data, prior_auth, intake, audit, shared) — not technical-layer soup |
| Comment-heavy / AI mush | **No restating comments**; Karpathy simplicity + surgical diffs |

---

## Success criteria

1. Readable inheritance — clear modules, domain language, decisions written down.
2. Correct business rules — submit validation, claim, COI, per-procedure decide, role-scoped reads.
3. Audit integrity — every state change has who/when; no approved without actor.
4. Partner-ready API — OpenAPI + actionable multi-field errors; synthetic seed only.
5. Explainability — defend every line; AI usage documented honestly.
6. Runnable locally in one command; CI proves build + tests without pushing images.

---

## Pre-code artifacts (Task 0 — do before scaffolding folders)

Write into `README.md` (Decisions) and keep short enough to draw on a whiteboard.

### A. State machine

```
[intake validation]
   ├─ fail → IntakeRejection (durable; NOT in review queue)
   └─ ok  → PriorAuthRequest status=submitted, claimed_by=NULL
                │
                ▼ claim (atomic)
         status=in_review, claimed_by=<reviewer>, claimed_at=now
                │
                ├─ admin reassign → claimed_by=<other reviewer> (still in_review)
                └─ decide (all procedures in one shot)
                       status=decided, decided_by, decided_at
                       each procedure: approved | denied (+ reason if denied)
                       TERMINAL — no further mutations
```

**Invariants**
- Only `submitted` + `claimed_by IS NULL` appear in review queue.
- Claim: `UPDATE … WHERE id=:id AND status='submitted' AND claimed_by_user_id IS NULL`.
- Decide requires actor = current claim holder (or document admin override — default: claim holder only).
- `decided` ⇒ `decided_by_user_id NOT NULL` (DB CHECK).
- Reviewer with COI edge to member cannot claim or decide.

### B. Audit matrix

| Action | Actor | Persist | Audit payload (min) |
|--------|-------|---------|---------------------|
| intake_reject | office user | `IntakeRejection` + optional `AuditEvent` | correlation_id, fields[], practice_id |
| submit | office user | request + procedures + `AuditEvent` | request_id, member_id, procedure codes |
| claim | reviewer | request claim fields + `AuditEvent` | request_id, reviewer_id |
| reassign | ops_admin | claim fields + `AuditEvent` | request_id, from, to |
| decide | reviewer | procedure decisions + decided_* + `AuditEvent` | per-procedure outcomes |

Write audit in the **same transaction** as the state change.

### C. Visibility matrix

| Field / capability | Member | Office (own practice) | Reviewer (queue/claimed) | Ops admin |
|--------------------|--------|----------------------|--------------------------|-----------|
| List/get requests | own only | own practice | queue unclaimed + own claimed (not others’ claimed) | all |
| clinical_note | ❌ | ✅ | ✅ | ✅ |
| denial_reason / reviewer reasoning | ❌ (show approved \| not approved only) | ✅ | ✅ | ✅ |
| Audit trail | ❌ | own practice optional | ❌ | ✅ |
| IntakeRejection lookup | ❌ | own practice by correlation_id | ❌ | all |

### D. Glossary (new-hire words)

- **PriorAuthRequest** — accepted submission that may enter the review queue.
- **IntakeRejection** — durable record of a failed submit; never appears in the queue.
- **Claim** — exclusive assignment of a submitted request to one reviewer.
- **COI** — reviewer treats that member; blocked from claim/decide.
- **Final** — `decided`; appeals out of scope.

---

## File map (clean root + domain packages)

Root holds only entrypoints and runtime project files. App code is split by **domain** (not by technical layer). Each domain owns its models, schemas, services, and router; `shared/` holds cross-cutting wiring.

```
.
├── AGENTS.md / CLAUDE.md / init.sh / README.md
├── pyproject.toml / uv.lock
├── Dockerfile / docker-compose.yml
├── .github/workflows/ci.yml
├── alembic.ini / alembic/versions/
├── app/
│   ├── main.py                 # app factory, include domain routers, lifespan
│   ├── config.py
│   ├── clock.py                # America/New_York today
│   ├── db.py                   # engine, session
│   ├── telemetry.py
│   ├── shared/                 # cross-cutting only
│   │   ├── errors.py           # problem+json / field error shapes
│   │   └── deps.py             # get_db, shared FastAPI deps
│   ├── identity/               # users, JWT, RBAC
│   │   ├── models.py
│   │   ├── auth.py             # Bearer parse + require_role
│   │   └── schemas.py          # UserContext if needed
│   ├── master_data/            # practices, members, coverage, links, COI
│   │   ├── models.py
│   │   └── seed_helpers.py     # optional; or keep seed in scripts/
│   ├── prior_auth/             # request lifecycle (office + reviewer + admin + member reads)
│   │   ├── models.py           # PriorAuthRequest, PriorAuthProcedure
│   │   ├── schemas.py          # request/response + role-specific views
│   │   ├── services/
│   │   │   ├── submit.py
│   │   │   ├── claim.py
│   │   │   ├── decide.py
│   │   │   └── reassign.py
│   │   └── router.py           # /v1/prior-auths, /v1/review-queue, /v1/me/prior-auths
│   ├── intake/                 # failed submissions (not in queue)
│   │   ├── models.py           # IntakeRejection
│   │   ├── services.py
│   │   └── router.py           # /v1/support/intake-rejections/{correlation_id}
│   └── audit/                  # append-only trail
│       ├── models.py           # AuditEvent
│       ├── writer.py           # same-session writer
│       └── router.py           # GET …/audit (admin)
├── tests/                      # mirror domains: test_prior_auth_*, test_intake_*, …
├── scripts/
├── postman/
├── harness/
└── docs/
    ├── plans/
    ├── council/
    └── harness/
```

**Rules:** No `repos/` package unless duplication appears twice. Routers stay thin; domain `services/` hold rules (mutmut targets `app/*/services` and `app/prior_auth/services`). Do not create empty domains “for later.”

---

## Domain model

```
Practice ──< PatientPracticeLink >── Member
Member ──< Coverage (effective_from / effective_to)
User (id, role, optional practice_id / member_id / reviewer linkage)
ReviewerMemberConflict (reviewer_user_id, member_id)

PriorAuthRequest
  id, member_id, practice_id, submitted_by_user_id
  diagnosis_icd10, date_of_service, clinical_note (nullable)
  status: submitted | in_review | decided
  claimed_by_user_id (nullable), claimed_at
  decided_at, decided_by_user_id (nullable; CHECK with status)

PriorAuthProcedure
  request_id, code, units, sequence
  decision: pending | approved | denied
  denial_reason (required if denied)

IntakeRejection
  id, correlation_id (unique), actor_user_id, practice_id
  at, payload_snapshot (json), field_errors (json)

AuditEvent (append-only)
  id, request_id (nullable), intake_rejection_id (nullable)
  actor_user_id, action, at, payload (json)
```

---

## API surface

Base: `/v1` · Auth: `Authorization: Bearer <token>`

### Shared
- `GET /v1/health`
- OpenAPI via FastAPI `/docs`

### Provider office
- `POST /v1/prior-auths` — submit (422 multi-error **and** persist IntakeRejection on validation failure; return `correlation_id`)
- `GET /v1/prior-auths` — list own practice
- `GET /v1/prior-auths/{id}` — detail own practice

### Reviewer
- `GET /v1/review-queue` — unclaimed `submitted`
- `POST /v1/prior-auths/{id}/claim`
- `POST /v1/prior-auths/{id}/decision` — all procedures in one shot

### Ops admin
- `GET /v1/prior-auths` — all
- `POST /v1/prior-auths/{id}/reassign` — `{ reviewer_id }`
- `GET /v1/prior-auths/{id}/audit`
- `GET /v1/support/intake-rejections/{correlation_id}`

### Member
- `GET /v1/me/prior-auths`
- `GET /v1/me/prior-auths/{id}` — redacted

### Office support (own practice)
- `GET /v1/support/intake-rejections/{correlation_id}` — practice-scoped

**Deferred from MVP, later shipped** (wishlist plan `2026-11-25-wishlist-outbox-maildev.md`): notify-on-decision (outbox→MailDev), reviewer workload, Idempotency-Key, auditor role.

---

## Business rules checklist

### Submission
- [ ] Actor is `provider_office` with `practice_id`
- [ ] Member linked to that practice
- [ ] DOS ≥ today (America/New_York)
- [ ] DOS ≤ today + 365 days
- [ ] Active coverage overlapping DOS
- [ ] ≥1 procedure; CPT/HCPCS + units ≥ 1
- [ ] Units > 30 → hard reject with clear “likely typo” message
- [ ] ICD-10 present (light format check)
- [ ] Clinical note optional
- [ ] Failures: multi-error list + `correlation_id` + `IntakeRejection` row

### Review
- [ ] Queue = `submitted` AND unclaimed
- [ ] Atomic claim
- [ ] COI → 403
- [ ] Decision covers every procedure; deny needs reason
- [ ] Transition to `decided` with `decided_by` + audit; DB CHECK
- [ ] No mutations after decided

### Visibility / compliance
- [ ] Member serializers strip note + denial reasons
- [ ] Office practice-scoped; admin all; reviewers queue + own claimed
- [ ] Audit on submit, claim, reassign, decide, intake_reject

---

## Version policy (latest stable / long-support)

Python and PostgreSQL do not brand “LTS” like Node; each supported major gets multi-year maintenance (~5y). **Policy:** newest **stable** major of each runtime + newest **stable** PyPI release of each library at Task 1. No alphas/RCs. Lock with `uv.lock`. Re-check PyPI/Docker on scaffold — floors below are dated **2026-11-24**.

| Component | Group | Floor / pin | Notes |
|-----------|-------|-------------|--------|
| Python | runtime | `3.15` / `python:3.15.2-slim` | Latest stable major |
| PostgreSQL | runtime | `postgres:19` | Latest stable major |
| fastapi | **prod** | ≥0.165.0 | `[project].dependencies` |
| uvicorn[standard] | **prod** | ≥0.54.0 | |
| sqlalchemy | **prod** | ≥2.1.9 | |
| alembic | **prod** | ≥1.20.1 | Needed to migrate in deploy/CI |
| pydantic / pydantic-settings | **prod** | ≥2.14.4 / ≥2.16.3 | |
| pyjwt | **prod** | ≥2.15.1 | |
| psycopg[binary] | **prod** | ≥3.3.9 | |
| opentelemetry-api / sdk / exporter-otlp | **prod** | ≥1.45.2 | |
| opentelemetry-instrumentation-* | **prod** | match SDK (e.g. 0.66b2) | Upstream `0.xbY` pairing |
| httpx2 | **dev** | ≥2.0.0 | Starlette/FastAPI TestClient (httpx deprecated) |
| pytest | **dev** | ≥9.2.0 | |
| mutmut | **dev** | ≥3.8.1 | |
| ruff | **dev** | ≥0.17.6 | |

`requires-python = ">=3.15"`. CI: Python 3.15 + Postgres 19; `uv sync` (with dev). Image build: `--no-dev`.

**uv layout (required):**

```toml
[project]
requires-python = ">=3.15"
dependencies = [
  # prod only — fastapi, uvicorn, sqlalchemy, alembic, pydantic*, pyjwt, psycopg, otel*
]

[dependency-groups]
dev = [
  # pytest, httpx, mutmut, ruff — never in the runtime image
]
```

Commands: `uv add fastapi …` · `uv add --dev pytest httpx mutmut ruff` · local `uv sync` · Docker `uv sync --frozen --no-dev`.

## Stack & ops details

| Layer | Choice | Notes |
|-------|--------|-------|
| Packages | `uv` | Prod vs `[dependency-groups] dev`; latest stables → `uv.lock` |
| Runtime | Python 3.15 + Postgres 19 | Latest stable majors |
| API | FastAPI (latest stable) | OpenAPI for partners |
| ORM | SQLAlchemy 2 + Alembic (latest stable) | Migrations required |
| Auth | PyJWT HS256 (latest stable) | Seed tokens in README |
| Observability | OpenTelemetry | Logs + metrics required; request_id / correlation_id |
| Run | Compose + multi-stage Dockerfile | Non-root runtime; no build tools in final image |
| Tests | pytest + httpx ASGI (user-flow) | Mock only DB / externals |
| Mutation | mutmut | Scoped to `app/prior_auth/services` (+ intake services) |
| CI | GitHub Actions | Build image **no push**; pytest; mutmut |

### Dockerfile shape (multi-stage)

1. **builder** — uv on Python 3.15; **`uv sync --frozen --no-dev`** (prod deps only) into `/app`
2. **runtime** — `python:3.15.2-slim` (or newer 3.15.x-slim); copy venv + app; `USER` non-root; `CMD` uvicorn  
   Verify image has no pytest/ruff/mutmut: e.g. `docker run … python -c "import pytest"` must fail.

Compose DB service: `image: postgres:19` (or `postgres:19.0`). Local API container may use a prod image; run tests on the host / CI with `uv sync` (dev included).

### OpenTelemetry MVP

- Instrument FastAPI + SQLAlchemy (or DBAPI) + logging bridge
- Export: console / OTLP env-configured (`OTEL_EXPORTER_OTLP_ENDPOINT` optional)
- Metrics: request counts, claim conflicts, intake rejection counts (low cardinality)
- Always attach `request_id`; on intake failure attach `correlation_id`

### GitHub Actions (`ci.yml`) outline

```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services: postgres:19 (health-checked)
    steps: checkout → setup uv → uv sync (includes dev group) → alembic upgrade → pytest
  mutate:
    needs: test
    steps: checkout → setup uv → uv sync → mutmut on app/prior_auth/services (documented threshold)
  image:
    runs-on: ubuntu-latest
    steps: checkout → docker build -t prior-auth-api:ci .   # NO push, NO login
```

---

## Implementation tasks

### Task 1: Matrices in README + local skeleton

**Files:**
- Create: `README.md`, `pyproject.toml`, `.python-version`, `app/__init__.py`, `app/main.py`, `app/config.py`, `app/clock.py`, `app/telemetry.py` (`CLAUDE.md` already at root)
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.github/workflows/ci.yml` (stub job OK)
- Optional: `.cursor/rules/karpathy-guidelines.mdc` with `alwaysApply: true`

**Interfaces:**
- Produces: `get_today() -> date` in `app/clock.py` using `America/New_York`
- Produces: `setup_telemetry(app) -> None`
- Produces: FastAPI app with `GET /v1/health` → `{"status":"ok"}`

- [ ] **Step 1:** Write README Decisions: state machine, audit matrix, visibility matrix, glossary, units>30 hard reject rationale, cut list (outbox/idempotency/wishlist), coding standards one-liner (ponytail + Karpathy + no noise comments).
- [ ] **Step 2:** Add `CLAUDE.md`; `uv` project with `requires-python = ">=3.15"`, `.python-version` = `3.15`. Add **prod** with `uv add …` and **dev** with `uv add --dev pytest httpx mutmut ruff` (Version policy floors; refresh to current stable). → verify: `uv lock` succeeds; `pyproject.toml` has `[dependency-groups] dev`; prod list excludes pytest/ruff/mutmut/httpx; `uv run python -c "import sys; assert sys.version_info[:2] == (3, 15)"`.
- [ ] **Step 3:** Implement `clock.py`, minimal FastAPI health, thin OTel setup in lifespan. → verify: `uv sync && uv run pytest` (or health smoke).
- [ ] **Step 4:** Multi-stage Dockerfile (`python:3.15.2-slim`, **`uv sync --frozen --no-dev`**) + Compose (`postgres:19`). → verify: `docker compose up --build` + health curl; image lacks pytest.
- [ ] **Step 5:** Commit locally: `chore: skeleton with uv, otel, compose, decisions`.

---

### Task 2: Schema, migrations, seed, JWT auth

**Files:**
- Create: `app/db.py`, `app/identity/` (models, auth), `app/master_data/models.py`, `app/prior_auth/models.py`, `app/intake/models.py`, `app/audit/models.py`, `alembic/*`, `scripts/seed.py`
- Create: `tests/conftest.py` (DB fixture, token helpers)

**Interfaces:**
- Produces: models for User, Member, Practice, Coverage, PatientPracticeLink, ReviewerMemberConflict, PriorAuthRequest, PriorAuthProcedure, IntakeRejection, AuditEvent
- Produces: `get_current_user(token) -> UserContext(user_id, role, practice_id?, member_id?)`
- Produces: DB CHECK / constraint names documented in migration for decided⇒actor
- Produces: seed users + printed JWT tokens table in README

- [ ] **Step 1:** Failing test: seed user JWT authorizes health-adjacent protected ping or `require_role`.
- [ ] **Step 2:** Alembic initial migration with CHECK constraint + indexes for queue (`status`, `claimed_by_user_id`).
- [ ] **Step 3:** Seed script: members, practices, links, coverage, reviewers (incl. one COI pair), office, admin, member users.
- [ ] **Step 4:** Verify migrate + seed via Compose; document tokens.
- [ ] **Step 5:** Commit: `feat: schema, seed, jwt auth`.

---

### Task 3: Slice A — Submit + intake rejection + office read + audit

**Files:**
- Create: `app/prior_auth/services/submit.py`, `app/prior_auth/schemas.py`, `app/prior_auth/router.py`, `app/intake/` (models, services, router), `app/audit/writer.py`, `app/shared/errors.py`
- Test: `tests/test_submit.py`, `tests/test_intake_support.py`

**Interfaces:**
- Consumes: `get_today()`, `UserContext`, models
- Produces: `submit_prior_auth(ctx, body) -> PriorAuthRequest | raises ValidationFailure(correlation_id, errors)`
- Produces: `GET /v1/support/intake-rejections/{correlation_id}`

- [ ] **Step 1:** Red tests — unlinked patient; past DOS; >1 year; no coverage; units 31; happy path → `submitted` + audit; intake support lookup by correlation_id.
- [ ] **Step 2:** Implement validation collecting **all** field errors; on failure write `IntakeRejection` + audit; on success write request/procedures + audit in one transaction.
- [ ] **Step 3:** Office list/get practice-scoped.
- [ ] **Step 4:** `uv run pytest tests/test_submit.py tests/test_intake_support.py -v` PASS.
- [ ] **Step 5:** Commit: `feat: submit path with intake rejection and audit`.

---

### Task 4: Slice B — Queue, claim, COI, decide, reassign

**Files:**
- Create: `app/prior_auth/services/{claim,decide,reassign}.py`; extend `app/prior_auth/router.py`
- Test: `tests/test_claim_concurrency.py`, `tests/test_coi.py`, `tests/test_decide.py`, `tests/test_db_invariants.py`

**Interfaces:**
- Produces: `claim_request(reviewer, id) -> PriorAuthRequest` (atomic; 409 if lost race)
- Produces: `decide_request(reviewer, id, outcomes) -> PriorAuthRequest`
- Produces: `reassign_request(admin, id, reviewer_id) -> PriorAuthRequest`

- [ ] **Step 1:** Red tests — concurrent claim exactly one wins; COI 403; decide missing procedure 422; deny without reason 422; decided cannot reassign/redecide; DB invariant decided_by present.
- [ ] **Step 2:** Implement claim SQL with row lock / conditional update; COI check; decide all-or-nothing; admin reassign; audit each.
- [ ] **Step 3:** `uv run pytest` for claim/coi/decide PASS.
- [ ] **Step 4:** Commit: `feat: review queue claim decide reassign`.

---

### Task 5: Slice C — Member redaction + audit API + OpenAPI polish

**Files:**
- Modify: `app/prior_auth/schemas.py`, `app/prior_auth/router.py` (member views); create `app/audit/router.py`
- Test: `tests/test_member_redaction.py`

**Interfaces:**
- Produces: member response model without `clinical_note`, without `denial_reason` (procedure status as approved | not_approved)

- [ ] **Step 1:** Red test — member GET never includes note or denial reason after deny.
- [ ] **Step 2:** Implement member endpoints + admin audit GET; tighten OpenAPI descriptions/examples for error shape (`error_code`, `field`, `message`, `correlation_id`).
- [ ] **Step 3:** Pytest PASS; commit: `feat: member redaction and audit read`.

---

### Task 6: CI, mutmut, image build, live-demo + Postman generator

**Files:**
- Modify: `.github/workflows/ci.yml`, `Dockerfile`, `pyproject.toml` / `mutmut_config.py`
- Create: `scripts/demo.sh` (5 curls: submit fail → support lookup → submit ok → claim race note → COI → decide → member redaction)
- Create: `scripts/generate_postman_collection.py` — builds Postman Collection v2.1 + environment from the live FastAPI OpenAPI (no hand-maintained request list)
- Create: `postman/Prior_Auth_API.postman_collection.json`, `postman/Prior_Auth_API.postman_environment.json` (generated artifacts; regenerate in CI or docs step)
- Modify: `README.md` — how to run, tokens, AI usage stub, decisions, CI notes, Postman import steps

**Interfaces:**
- Produces: CI green on pytest + docker build (no push) + mutmut scoped to `app/prior_auth/services`
- Produces: demo script runnable after `docker compose up` + seed
- Produces: `uv run python scripts/generate_postman_collection.py` → collection with all `/v1` routes, Bearer `{{token}}`, and env vars for seeded role tokens (`office_token`, `reviewer_token`, `member_token`, `admin_token`, `base_url`)

**Postman generator rules (ponytail):**
- Source of truth = `app.openapi()` (or `GET /openapi.json`); do not duplicate paths by hand.
- Stdlib + already-installed deps only (json + FastAPI app import); no new Postman SDK unless forced.
- Collection auth: Bearer `{{token}}`; folder by tag/path prefix if OpenAPI tags exist.
- Environment file carries seed JWTs from the same values documented in README/seed.
- README: `uv run python scripts/generate_postman_collection.py` then Import → collection + environment in Postman.

- [ ] **Step 1:** Wire CI jobs: test (Postgres service), mutate (`mutmut run` paths=`app/prior_auth/services`), image (`docker build` only).
- [ ] **Step 2:** Run mutmut locally; kill survivors in prior_auth services until threshold met (document in README).
- [ ] **Step 3:** Write `scripts/demo.sh` + README “Live walkthrough” section.
- [ ] **Step 4:** Implement `scripts/generate_postman_collection.py`; run it; commit generated `postman/*.json`; document import in README. → verify: collection contains submit/claim/decide/me/support paths and env has four role tokens.
- [ ] **Step 5:** Full local verify: compose up, seed, pytest, demo.sh, postman generate, docker build.
- [ ] **Step 6:** Commit: `ci: github actions build+test+mutmut; demo + postman generator`.

---

### Task 7: Self-review for live session (no feature work)

- [ ] Draw state machine from memory.
- [ ] Show claim race test + SQL.
- [ ] Show member redaction test + schema.
- [ ] Show audit rows for a decided request + IntakeRejection support path.
- [ ] Be ready for a small live change (e.g. add auditor read-only audit route).
- [ ] Finalize README “How AI was used”.

---

## Testing strategy (locked)

**Shape:** Outside-in, same path a partner/office/reviewer uses.

1. **Act via HTTP** — `httpx.ASGITransport` / FastAPI test client against the real app: real routes, middleware, JWT auth deps, Pydantic validation, services, audit writer, response schemas.
2. **Do not mock** routers, services, domain rules, RBAC dependencies, serializers, OpenAPI, or “call the service directly and skip HTTP” for acceptance of business rules.
3. **Allowed mocks only:**
   - **DB responses** at the persistence boundary (session/repository), when the test is proving API/service behavior without needing a live engine; **or**
   - **External calls** (outbound HTTP, email, third-party APIs, OTel exporter). MVP has almost no externals — mock those if introduced.
4. **Exception — persistence truth:** claim race, DB CHECK (`decided ⇒ decided_by`), and audit-in-same-transaction proofs use a **real Postgres** fixture (Compose/Testcontainers). There the database is part of the system under test, not a mocked collaborator. Do not fake those with in-memory stubs.
5. **Fixtures:** seed (or factory) master data + mint real JWTs for roles; assert status codes + JSON bodies (+ optional DB row checks only on persistence-truth tests).
6. **mutmut** targets `app/prior_auth/services` (and intake services if non-trivial); survivors must not be fixable by “tests that only hit mocks of the service.”

### Anti-patterns (reject in review)

- Patching `submit_prior_auth` while the test “POSTs” to the API  
- Mocking Pydantic / skipping validation  
- Calling service functions as the primary proof that an endpoint works  
- Broad `MagicMock` of the app or `dependency_overrides` that replace business services (overrides OK only to inject a fake DB session or fake external client)
- Copy-pasted HTTP/setup in tests — use `tests/conftest.py` helpers or `@pytest.mark.parametrize`; add a helper on the second copy
- Duplicated domain logic across services/routers — extract shared utils (e.g. `services/common.py`, `raise_validation`) when the pattern appears twice

### Commit / CI quality gates (locked)

- **ruff** format + lint on `app` `tests` `scripts`
- **call-style** — no nested non-constructor calls / `IfExp` / BoolOp / lambda in call args (`scripts/check_call_style.py`)
- **FastAPI compile** — `scripts/check_fastapi_compile.py` in pre-commit gates and CI
- **pytest** with **100%** line+branch coverage
- **Visible step summaries** on every gates/CI step (`### …` + `$GITHUB_STEP_SUMMARY`)
- Local: `./scripts/gates.sh`; pre-commit may set `GATES_SKIP_TESTS=1` (full suite still in CI / `./init.sh`)

## Test plan (minimum)

Each case below is an **HTTP** scenario unless marked persistence-truth.

1. Submit happy path → `submitted` + audit (HTTP; persistence-truth optional assert on rows).
2. Unlinked patient → 422 + correlation_id (+ IntakeRejection via HTTP support lookup or DB assert).
3. Past DOS / >1 year / no coverage / units 31 (HTTP).
4. Two concurrent claims → exactly one wins (**persistence-truth**, real Postgres).
5. COI reviewer → 403 (HTTP).
6. Decide without all procedures → 422 (HTTP).
7. Deny without reason → 422 (HTTP).
8. Member GET — no note, no denial reason (HTTP body).
9. Decided cannot reassign/redecide (HTTP).
10. Decided row always has `decided_by_user_id` (**persistence-truth** + HTTP decide).
11. Support GET intake rejection by correlation_id (HTTP).
12. mutmut: no trivial survivors in submit/claim/decide services.

---

## README outline (submission)

1. How to run — `uv`, Compose, migrate, seed, example curls + tokens.
2. Decisions & assumptions — matrices + units>30 + TZ + cut list + coding standards (ponytail full, Karpathy, no noise comments).
3. How AI was used — prompts, wrong turns, council, what changed.
4. API overview + `/docs` + **Postman**: generate script + import collection/environment.
5. Design notes — flat modules, audit-in-transaction, RBAC, OTel, CI (build no push).
6. Live walkthrough — `scripts/demo.sh`.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Overbuilding wishlist | Cut until Task 7 spare time only; ponytail YAGNI |
| mutmut noise / time | Scope to `app/prior_auth/services`; document threshold |
| OTel ceremony | Thin `telemetry.py`; console exporter default |
| Status mush | Matrices first; DB CHECKs |
| Audit bolted on late | `app/audit/writer.py` in same transaction from Task 3 |
| AI mush / comment noise | Karpathy simplicity; names over comments; thin routers, fat domain services |
| Package sprawl | Domain packages only; no `repos/` until duplication; no empty domains |

---

## Fail-closed hour budget

| If time left | Ship |
|--------------|------|
| Must | Matrices, submit+intake, claim+decide, member redaction, audit, compose, pytest, README |
| Should | CI + docker multi-stage + mutmut + demo.sh + Postman generator + OTel metrics |
| Nice | Admin workload note in README only; auditor seam comment |

---

## Helpful skills found under `~/projects` (use when implementing)

Scan result: no existing Postman generator script — **build it in Task 6 / feat-006**. Useful skills elsewhere:

| Skill | Path | Use for |
|-------|------|---------|
| harness-creator | `personal/learn-harness-engineering/skills/harness-creator` | Already applied |
| ponytail | `attendi/api/.cursor/skills/ponytail` (+ plugin) | Keep diffs minimal |
| llm-council | `attendi/api/.cursor/skills/llm-council` | Already used on plan |
| fastapi-patterns | `ECC/skills/fastapi-patterns` | App layout, DI, httpx tests |
| api-design | `ECC/skills/api-design` + `ECC/.agents/skills/api-design` | `/v1` resources, errors, status codes |
| backend-patterns | `ECC/skills/backend-patterns` | Service/transaction layering |
| postgres-patterns | `ECC/skills/postgres-patterns` | CHECK/indexes, claim race SQL |
| docker-patterns | `ECC/skills/docker-patterns` | Multi-stage image hygiene |
| python-testing | `ECC/skills/python-testing` | pytest patterns |
| tdd-workflow | `ECC/skills/tdd-workflow` + `.agents` | Red→green per feature |
| python-patterns | `ECC/skills/python-patterns` | Idiomatic Python |
| security-review | `ECC/skills/security-review` | Fake JWT / RBAC review before submit |
| create-migration / migration | `attendi/api/.claude/skills/` | Alembic habits (adapt to this repo) |
| verify | `attendi/.claude/skills/verify` | Runtime curl/Postman evidence after slices |

**Skip for this API take-home:** frontend/design/animation skills under `financial-tracker` and most of `attendi` mobile/UI skills.

---

## Agent harness (complete)

| Subsystem | Artifact |
|-----------|----------|
| Instructions | `AGENTS.md` + `CLAUDE.md` (repo root) |
| Inventory | `harness/feature_list.json` (all `done`) |
| Snapshot | `harness/session-handoff.md`, `harness/progress.md` |
| Verification | `./init.sh`, `./scripts/gates.sh`, `./scripts/demo.sh` |
| Plans | `docs/plans/` (historical; shipped) |
| Council | `docs/council/` (planning notes for README “How AI was used”) |

Feature IDs: feat-001…007 ↔ MVP tasks; feat-008…012 ↔ wishlist (also shipped).

## Submission

1. `./init.sh` + `./scripts/demo.sh` green
2. Private template copy / push; add collaborator `rgavrilov5`

---

## Reference

- Challenge: https://github.com/rgavrilov5/prior-auth-api-challenge
- Council: `docs/council/council-report-20261124-230109.html` / `docs/council/council-transcript-20261124-230109.md`
- Harness course: https://github.com/walkinglabs/learn-harness-engineering
- Skills inventory: ECC (`fastapi-patterns`, `api-design`, …), attendi (`ponytail`, `verify`, migrations), this repo `harness/` + `docs/`
