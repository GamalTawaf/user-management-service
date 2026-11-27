#!/bin/bash
set -euo pipefail

echo "=== Harness Initialization ==="
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=== Harness files present ==="
test -f AGENTS.md
test -f CLAUDE.md
test -f .agent/README.md
test -d .agent/rules
test -d .agent/skills
test -f .agent/feature_list.json
test -f .agent/progress.md
test -f .agent/session-handoff.md
test -f docs/plans/2026-11-24-prior-auth-api.md

if [[ ! -f pyproject.toml ]]; then
  echo "=== Skeleton not created yet (no pyproject.toml) ==="
  echo "Active work: feat-001 Decisions + local skeleton"
  echo "Plan: docs/plans/2026-11-24-prior-auth-api.md"
  echo "State: .agent/feature_list.json"
  echo "=== Pre-code harness OK ==="
  exit 0
fi

echo "=== uv sync (prod + dependency-groups.dev) ==="
uv sync

if [[ -d .git ]]; then
  echo "=== install git pre-commit gates ==="
  ./scripts/install_git_hooks.sh
fi

echo "=== commit/CI gates (ruff, call-style, fastapi compile, pytest) ==="
./scripts/gates.sh

if [[ -f Dockerfile ]]; then
  echo "=== docker build -t prior-auth-api:local . (no push) ==="
  docker build -t prior-auth-api:local .
fi

echo "=== Verification Complete ==="
