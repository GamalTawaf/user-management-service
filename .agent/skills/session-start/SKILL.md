---
name: session-start
description: >-
  Use at the start of a coding session on this prior-auth repo. Syncs git, loads
  the short harness reading path, and skips full historical plans unless needed.
---

# Session start

## Read (in order)

1. `AGENTS.md` (status + working rules)
2. `.agent/session-handoff.md` (system snapshot)
3. `README_FULL.md` Decisions only if touching domain behavior
4. Full `docs/plans/*` **only** when changing design or reopening shipped scope

## Git

```bash
git fetch origin
git checkout main && git pull origin main   # if starting fresh work
git rev-list --left-right --count HEAD...origin/main
```

## Then

- No new product scope unless the user asks (feat-001…012 done)
- Parallel agents → load `grit-parallel`
- Shipping → load `open-pr` / `stacked-prs` as needed
- Before claiming done → `./scripts/gates.sh`
