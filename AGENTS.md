# AGENTS.md

Prior Authorization API (public portfolio copy of Oxbridge Health take-home work). Durable Python + PostgreSQL backend a teammate inherits; defendable in a 45-minute walkthrough.

## Status

**Complete.** Features feat-001…012 in `.agent/feature_list.json` are `done` (core + wishlist). Do not invent new product scope unless the user asks. Prefer surgical fixes and walkthrough readiness over new features.

## Startup

1. `pwd` → repo root; load skill `.agent/skills/session-start` when beginning a session
2. Read this file, `CLAUDE.md`, and `README_FULL.md` Decisions (domain changes only)
3. `./init.sh` (repair baseline before any new work)
4. `.agent/session-handoff.md` for current system snapshot
5. Plans are historical: `docs/plans/2026-11-24-prior-auth-api.md`, `docs/plans/2026-11-25-wishlist-outbox-maildev.md` (**shipped**)

**Shared agent tree:** `.agent/` (inventory, handoff, rules, skills). Cursor auto-loads rules/skills via symlinks under `.cursor/`.

**On-demand skills:** `.agent/skills/{session-start,open-pr,grit-parallel,stacked-prs}/`

## Working rules

- **Ponytail full + Karpathy** — YAGNI, surgical diffs, every step has a verify check
- **No noise comments** — comment only when *why* is invisible
- **Tests = user flow** — real HTTP; mock only DB/external boundaries; never mock routers/services/schemas/RBAC. Claim race + DB CHECKs use real Postgres
- **Verification** — `./scripts/gates.sh` (and feature verify) before claiming done; update `.agent/progress.md` / handoff if state changes
- **Versions** — Python 3.15 + Postgres 19; latest stable PyPI (no alphas/RCs; OTel instrumentations may be `0.xbY`). `uv` only: prod in `[project].dependencies`, test/lint in `[dependency-groups] dev`
- **Never cut** — audit, RBAC, validation, plan-required tooling (uv, OTel, multi-stage Docker, mutmut, CI)
- **Parallel agents → grit** — if 2+ agents may edit overlapping code, use [grit](https://github.com/rtk-ai/grit): `grit claim` → work only in `.grit/worktrees/<agent>/` → `grit done`. Reindex with `./scripts/grit_reindex.sh` after big tree changes (parks `.worktrees` / `.venv` / `mutants` — grit does not skip those top-level dirs). Single-agent / non-overlapping work: plain branch + PR is enough. **Alembic:** serialize migration heads even under grit (AST locks do not merge graphs). Main checkout must be clean before `grit done`.

## Coding & quality gates

Mirrored in `.agent/rules/coding-gates.mdc`.

### No duplication

- **Tests:** reuse `tests/conftest.py` helpers (`submit_ok`, `submit_and_claim`, `claim_as`, `decide_as`, `reassign_as`, `assert_has_error_code`, `role_headers`, race helpers, …). Parametrize same shapes. Add a helper when a sequence appears twice.
- **App:** extract shared utils at 2+ call sites (`has_coi`, `get_request`, `audit_commit_refresh`; `raise_validation` / `raise_field`). No speculative layers for one site.

### Call style (`scripts/check_call_style.py`)

- No `IfExp` / `and`/`or` BoolOp / `Lambda` inside call **arguments** (`app/` + `tests/`).
- No nested non-constructor Calls inside call arguments (`app/` only; models/schemas exempt). CapWords constructors OK.
- Extract locals before the call.

### Lint / gates / CI

- **ruff** format + check on `app` `tests` `scripts`
- **FastAPI compile** (`scripts/check_fastapi_compile.py`)
- **pytest** 100% line + branch (`fail_under = 100`)
- Claim done only after `./scripts/gates.sh` green
- Every gates/CI step prints a visible summary (`### …` + `$GITHUB_STEP_SUMMARY` when set)

## Layout

```
.                         # entrypoints + runtime project files only
├── AGENTS.md / CLAUDE.md / init.sh
├── .agent/               # inventory, handoff, rules, skills (Cursor: `.cursor/` symlinks)
├── docs/plans/           # historical implementation plans (shipped)
├── app/
│   ├── shared/           # errors, deps
│   ├── identity/         # users, JWT, RBAC
│   ├── master_data/      # practices, members, coverage, COI
│   ├── prior_auth/       # submit/claim/decide/reassign + routers
│   ├── intake/           # IntakeRejection + support lookup
│   ├── audit/            # AuditEvent + writer + audit router
│   └── outbox/           # decision notify (worker + MailDev)
├── tests/ / scripts/ / postman/
```

## Artifacts

| Path | Role |
|------|------|
| `.agent/` | Inventory, handoff, rules, skills (any agent); Cursor via `.cursor/` symlinks |
| `.agent/feature_list.json` | Shipped feature inventory + evidence |
| `.agent/progress.md` | Compact shipped log |
| `.agent/session-handoff.md` | System snapshot + walkthrough |
| `README.md` | Quick start + Postman walkthrough |
| `README_FULL.md` | Decisions, CI, AI usage, full how-to-run |
| `./init.sh` / `./scripts/gates.sh` / `./scripts/demo.sh` | Verify + live demo |

## Verification

```bash
./init.sh
./scripts/gates.sh
./scripts/demo.sh
```

- Pre-commit: gates with `GATES_SKIP_TESTS=1` (includes postman fresh; full pytest still in CI / `./init.sh`)
- Mutmut: `./scripts/run_mutmut.sh` (CI / hot-path gate; not every local init)
- Postman: `./scripts/generate_postman_collection.py` → commit `postman/Prior_Auth_API*.json` (desktop dumps stay gitignored); do not hand-edit JSON. Pre-commit/CI: `scripts/check_postman_collection.py`

## Pull requests — never commit to `main`

**No direct commits or pushes to `main`.** Always:

1. Branch from latest `main` (`git fetch origin && git checkout -b <branch> origin/main`)
2. Commit on that branch only
3. Push the branch and open a PR into `main` (`gh pr create --base main`)
4. Merge via PR (squash/merge on GitHub) — do not `git push origin main`

This applies to docs, `.agent/`, and code alike. Hotfixes are not exempt.

### Risk lanes

Exactly one label: `low` | `medium` | `high`. See `.agent/rules/pr-lanes.mdc`.

1. Classify from the **full** diff; mixed → highest lane
2. `./scripts/ensure_pr_labels.sh` if needed
3. `gh pr create/edit … --label <lane>` and `Lane: …` in Summary
4. Unsure whether behavior changed → **high**

## Escalation

- Architecture / compliance ambiguity → ask user
- Unclear requirements → `README_FULL.md` Decisions / plans; then ask
- Repeated test failures → update progress, stop expanding scope
