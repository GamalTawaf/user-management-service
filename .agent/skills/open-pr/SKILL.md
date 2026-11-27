---
name: open-pr
description: >-
  Use when opening or updating a GitHub PR for this repo. Ensures branch-from-main,
  lane label, gh auth (unset stale GITHUB_TOKEN), and an accurate PR body.
---

# Open / update PR

## Steps

1. `git fetch origin` — branch must include what you intend; base is `main`.
2. Confirm not on `main` for commits: work on `docs/…` or `feat/…` only.
3. `unset GITHUB_TOKEN` before `gh` if auth fails with 401 (keyring account is valid).
4. `./scripts/ensure_pr_labels.sh`
5. Classify lane (`low` | `medium` | `high`) from **full** diff — see `.agent/rules/pr-lanes.mdc`.
6. Push: `git push -u origin HEAD`
7. Create:

```bash
gh pr create --base main --label <lane> --title "…" --body "$(cat <<'EOF'
## Summary
- Lane: **<lane>**
- …

## Test plan
- [ ] …

EOF
)"
```

8. If commits change the story (restore tooling, extra rules), `gh pr edit <n> --body …` immediately.

## Don't

- `git push origin main`
- Open unlabeled PRs
- Leave a stale description that contradicts the tip commit
