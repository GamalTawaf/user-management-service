#!/usr/bin/env bash
# Apply .github/repo-settings.json to the GitHub remote (squash-only + main protection).
# Requires: gh auth with admin on the repo. Branch protection needs a public repo or GitHub Pro.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SETTINGS="$ROOT/.github/repo-settings.json"
REPO="${GITHUB_REPOSITORY:-}"
TMPDIR_APPLY="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_APPLY"' EXIT

if [[ ! -f "$SETTINGS" ]]; then
  echo "missing $SETTINGS" >&2
  exit 1
fi

if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

echo "=== apply repo settings → $REPO ==="

python3 - "$SETTINGS" "$TMPDIR_APPLY" <<'PY'
import json
import sys
from pathlib import Path

settings = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])
(out / "repository.json").write_text(json.dumps(settings["repository"]))
bp = settings["branch_protection"]
(out / "branch.txt").write_text(bp["branch"])
payload = {
    "required_status_checks": bp["required_status_checks"],
    "enforce_admins": bp["enforce_admins"],
    "required_pull_request_reviews": bp["required_pull_request_reviews"],
    "restrictions": bp["restrictions"],
    "allow_force_pushes": bp["allow_force_pushes"],
    "allow_deletions": bp["allow_deletions"],
    "required_linear_history": bp["required_linear_history"],
    "required_conversation_resolution": bp["required_conversation_resolution"],
}
(out / "protection.json").write_text(json.dumps(payload))
PY

gh api -X PATCH "repos/$REPO" --input "$TMPDIR_APPLY/repository.json"

BP_BRANCH="$(cat "$TMPDIR_APPLY/branch.txt")"
gh api -X PUT "repos/$REPO/branches/$BP_BRANCH/protection" \
  --input "$TMPDIR_APPLY/protection.json"

echo "=== verify ==="
gh api "repos/$REPO" --jq '{allow_squash_merge,allow_merge_commit,allow_rebase_merge,delete_branch_on_merge}'
gh api "repos/$REPO/branches/$BP_BRANCH/protection" \
  --jq '{allow_deletions:.allow_deletions.enabled,allow_force_pushes:.allow_force_pushes.enabled,enforce_admins:.enforce_admins.enabled,contexts:.required_status_checks.contexts,strict:.required_status_checks.strict}'

echo "=== apply_github_repo_settings: PASSED ==="
