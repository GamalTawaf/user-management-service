#!/usr/bin/env bash
# Re-run `grit init` without indexing top-level noise dirs.
# grit skips path segments matching "/." but NOT top-level ".worktrees"/".venv".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
command -v grit >/dev/null || {
  echo "error: grit not on PATH (install: https://github.com/rtk-ai/grit)" >&2
  exit 1
}

PARK="$(mktemp -d /tmp/ums-grit-park.XXXXXX)"
cleanup() {
  for name in .worktrees .venv mutants; do
    if [[ -e "$PARK/$name" && ! -e "$ROOT/$name" ]]; then
      mv "$PARK/$name" "$ROOT/$name"
    fi
  done
  rmdir "$PARK" 2>/dev/null || true
}
trap cleanup EXIT

for name in .worktrees .venv mutants; do
  if [[ -e "$ROOT/$name" ]]; then
    mv "$ROOT/$name" "$PARK/$name"
  fi
done

rm -f "$ROOT/.grit/registry.db"
grit init
echo "### grit reindex"
grit symbols 2>/dev/null | wc -l | awk '{print "symbol listing lines:", $1}'
