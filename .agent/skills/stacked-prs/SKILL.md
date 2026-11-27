---
name: stacked-prs
description: >-
  Use when shipping a sequence of dependent PRs. Create the stack with GitHub’s
  gh stack extension; let GitHub manage bases/linking after submit—do not hand-rebase.
---

# Stacked PRs (GitHub native)

Use **[github/gh-stack](https://docs.github.com/en/pull-requests/get-started/stacked-prs-quickstart)** — not ad-hoc `git rebase` of each child onto `main`.

Docs: [Creating stacked PRs](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-stacked-pull-requests) · [CLI reference](https://docs.github.com/en/pull-requests/reference/stacked-prs-cli-commands)

## Setup (once)

```bash
unset GITHUB_TOKEN   # if gh 401s
gh extension install github/gh-stack
# needs gh ≥ 2.90, git ≥ 2.20 (2.36+ preferred)
```

## Create the stack

```bash
git fetch origin
gh stack init --base main <first-branch>   # or: gh stack init  (interactive)
# commit layer 1 on that branch

gh stack add <next-branch>                 # or: gh stack add -Am "msg"
# commit each layer; repeat add as needed

gh stack submit                            # push all + create/link stacked PRs
gh stack view                              # order, URLs, status
```

Each PR gets the correct base (layer N → layer N−1; bottom → `main`). GitHub links the stack; **merging/restacking is GitHub’s job** — do not manually rebase children onto `main` after each merge unless `gh stack` / the UI tells you to intervene.

## This repo extras

- One lane-homogeneous change per layer (`low` | `medium` | `high`).
- After `gh stack submit`, label each PR: `./scripts/ensure_pr_labels.sh` then `gh pr edit <n> --add-label <lane>` (and `Lane: …` in the body).
- **Alembic:** still one linear `down_revision` chain across layers (stack tooling does not merge migration graphs).
- Parallel overlapping edits across agents → grit (`grit-parallel`); stacking is for ordered PR landing, not AST locks.

## Don't

- Hand-roll `--base` + post-merge `git rebase origin/main` + `--force-with-lease` as the default stack workflow
- Merge stack layers out of order in a way that breaks the GitHub stack
- Bundle unrelated high-lane behavior into one layer to avoid stacking
