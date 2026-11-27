---
name: grit-parallel
description: >-
  Use when two or more agents will edit overlapping code in this repo. Runs grit
  claim/worktree/done and reindex; serializes Alembic heads.
---

# Grit parallel agents

## When

2+ agents might touch the same symbols/files. Single-agent or non-overlapping work → plain branch + PR is enough.

## Steps

1. Install grit on PATH if missing ([rtk-ai/grit](https://github.com/rtk-ai/grit)).
2. After large tree changes: `./scripts/grit_reindex.sh` (parks `.worktrees` / `.venv` / `mutants`).
3. `grit claim -a <agent> -i "<intent>" <path>::<symbol> …`
4. Work **only** under `.grit/worktrees/<agent>/`
5. Keep primary checkout **clean** before `grit done -a <agent>`
6. **Alembic:** one linear `down_revision` chain — finish one migration before another agent starts schema work

## Don't

- Edit the same files on two agents without grit claims
- Expect grit to merge migration graphs
- Delete `scripts/grit_reindex.sh` during “docs cleanup”
