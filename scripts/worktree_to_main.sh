#!/usr/bin/env bash
# Park a linked worktree and check its branch out in the primary clone so you
# can test (compose, etc.) from the main repo path. Restore with --done.
#
# Usage:
#   ./scripts/worktree_to_main.sh <worktree-path-or-branch> [--force]
#   ./scripts/worktree_to_main.sh --done [--force]
#
# Example:
#   ./scripts/worktree_to_main.sh .worktrees/fix-compose-db-dns
#   docker compose up --build
#   ./scripts/worktree_to_main.sh --done
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PRIMARY="$(git -C "$ROOT" worktree list --porcelain | awk '
  /^worktree / { path = substr($0, 10) }
  /^branch / {
    if (index(path, "/.worktrees/") == 0) { print path; exit }
  }
')"
if [[ -z "${PRIMARY}" ]]; then
  PRIMARY="$(git -C "$ROOT" rev-parse --show-toplevel)"
fi

STATE_FILE="$(cd "$(git -C "$PRIMARY" rev-parse --git-common-dir)" && pwd)/worktree-to-main.state"

die() { echo "error: $*" >&2; exit 1; }

require_clean() {
  local dir="$1"
  local label="$2"
  if [[ -n "$(git -C "$dir" status --porcelain)" ]]; then
    die "$label has uncommitted changes ($dir). Commit/stash or pass --force"
  fi
}

force=0
args=()
for a in "$@"; do
  case "$a" in
    --force|-f) force=1 ;;
    *) args+=("$a") ;;
  esac
done
set -- "${args[@]+"${args[@]}"}"

cmd="${1:-}"
[[ -n "$cmd" ]] || die "usage: $0 <worktree-or-branch> | --done [--force]"

if [[ "$cmd" == "--done" || "$cmd" == "done" ]]; then
  [[ -f "$STATE_FILE" ]] || die "no active switch (missing $STATE_FILE)"
  # shellcheck disable=SC1090
  source "$STATE_FILE"
  [[ -n "${BRANCH:-}" && -n "${WORKTREE:-}" && -n "${RETURN_BRANCH:-}" ]] \
    || die "corrupt state file: $STATE_FILE"

  if [[ "$force" != 1 ]]; then
    require_clean "$PRIMARY" "primary worktree"
  fi

  echo "=== return primary to ${RETURN_BRANCH} ==="
  git -C "$PRIMARY" checkout "$RETURN_BRANCH"

  if [[ -e "$WORKTREE" ]]; then
    die "worktree path already exists: $WORKTREE (remove it, then re-run --done)"
  fi
  echo "=== restore worktree ${WORKTREE} on ${BRANCH} ==="
  mkdir -p "$(dirname "$WORKTREE")"
  git -C "$PRIMARY" worktree add "$WORKTREE" "$BRANCH"
  rm -f "$STATE_FILE"
  echo "done: primary=${PRIMARY} @ ${RETURN_BRANCH}; worktree=${WORKTREE} @ ${BRANCH}"
  exit 0
fi

target="$cmd"
branch=""
worktree=""

if [[ -d "$target" ]]; then
  worktree="$(cd "$target" && pwd)"
  branch="$(git -C "$worktree" branch --show-current)"
  [[ -n "$branch" ]] || die "detached HEAD in $worktree — checkout a branch first"
elif git -C "$PRIMARY" show-ref --verify --quiet "refs/heads/$target"; then
  branch="$target"
  worktree="$(git -C "$PRIMARY" worktree list --porcelain | awk -v b="refs/heads/$branch" '
    /^worktree / { path = substr($0, 10) }
    /^branch / {
      if ($2 == b && index(path, "/.worktrees/") == 0) next
      if ($2 == b) { print path; exit }
    }
  ')"
elif git -C "$PRIMARY" show-ref --verify --quiet "refs/remotes/origin/$target"; then
  branch="$target"
else
  die "not a worktree path or local branch: $target"
fi

[[ "$worktree" != "$PRIMARY" ]] || die "refusing to operate on the primary worktree"
[[ -n "$branch" ]] || die "could not resolve branch"

if [[ -f "$STATE_FILE" ]]; then
  die "already switched (see $STATE_FILE). Run: $0 --done"
fi

if [[ "$force" != 1 ]]; then
  require_clean "$PRIMARY" "primary worktree"
  if [[ -n "$worktree" && -d "$worktree" ]]; then
    require_clean "$worktree" "worktree"
  fi
fi

return_branch="$(git -C "$PRIMARY" branch --show-current)"
[[ -n "$return_branch" ]] || die "primary checkout is detached"

if [[ -z "$worktree" ]]; then
  safe="${branch////-}"
  worktree="${PRIMARY}/.worktrees/${safe}"
fi

# Leave the worktree cwd before removing it (bash keeps this script in memory).
cd "$PRIMARY"

echo "=== park worktree (release branch ${branch}) ==="
if [[ -d "$worktree" ]]; then
  git worktree remove --force "$worktree"
else
  echo "no worktree directory at $worktree (branch already free)"
fi

echo "=== checkout ${branch} in primary ${PRIMARY} ==="
git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}" 2>/dev/null || true
git checkout "$branch"
git pull --ff-only origin "$branch" 2>/dev/null || true

cat >"$STATE_FILE" <<EOF
BRANCH=$branch
WORKTREE=$worktree
RETURN_BRANCH=$return_branch
EOF

echo "ready to test in: ${PRIMARY} (branch ${branch})"
echo "when done: ./scripts/worktree_to_main.sh --done"
