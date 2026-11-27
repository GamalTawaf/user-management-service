#!/bin/bash
set -euo pipefail

echo "=== User Management API init ==="
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

test -f AGENTS.md
test -f README.md
test -f pyproject.toml

echo "=== uv sync ==="
uv sync

if [[ -d .git ]]; then
  ./scripts/install_git_hooks.sh || true
fi

echo "=== gates ==="
./scripts/gates.sh

if [[ -f Dockerfile ]]; then
  docker build -t user-management-api:local .
fi

echo "=== Verification Complete ==="
