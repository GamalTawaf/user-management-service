#!/usr/bin/env bash
# Parallel mutmut: each child claims an exclusive user_mgmt_mutmut_{i} DB so
# DROP SCHEMA test_user_mgmt in pytest sessions does not race.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Optional ceiling while driving survivors to zero. Unset or 0 = require none.
MAX_SURVIVORS="${MUTMUT_MAX_SURVIVORS:-0}"

# Default children: 4 (override with MUTMUT_MAX_CHILDREN). Needs matching DBs.
MUTMUT_MAX_CHILDREN="${MUTMUT_MAX_CHILDREN:-4}"
export MUTMUT_MAX_CHILDREN
export MUTMUT_PARALLEL_DBS=1

# Default: wipe mutants/ so we do not print a stale 🎉/🙁 spinner at 0.00 mut/s.
# Set MUTMUT_KEEP_CACHE=1 to resume an interrupted run.
if [[ "${MUTMUT_KEEP_CACHE:-0}" != "1" ]]; then
  echo "=== clearing mutants/ cache (set MUTMUT_KEEP_CACHE=1 to keep) ==="
  rm -rf mutants
fi

echo "=== ensure mutmut DBs (user_mgmt_mutmut_0..$((MUTMUT_MAX_CHILDREN - 1))) ==="
uv run python scripts/ensure_mutmut_dbs.py "$MUTMUT_MAX_CHILDREN"

echo "=== mutmut (max-children=${MUTMUT_MAX_CHILDREN}) ==="
uv run mutmut run --max-children "$MUTMUT_MAX_CHILDREN" "$@"

results="$(uv run mutmut results 2>&1 || true)"
echo "$results"

# `mutmut results` lists survivors / not-checked only (killed mutants are omitted).
survived="$(printf '%s\n' "$results" | grep -c ': survived$' || true)"
unchecked="$(printf '%s\n' "$results" | grep -c ': not checked$' || true)"

echo "summary: survived=${survived} not_checked=${unchecked} max_survivors=${MAX_SURVIVORS}"

if [[ "${unchecked}" -gt 0 ]]; then
  echo "mutmut gate failed: ${unchecked} mutants not checked" >&2
  exit 1
fi

if [[ "${survived}" -gt "${MAX_SURVIVORS}" ]]; then
  echo "mutmut gate failed: ${survived} survivors > max ${MAX_SURVIVORS}" >&2
  exit 1
fi

echo "mutmut gate passed"
