#!/usr/bin/env bash
# Commit / CI gate runner. Each step prints a clear summary.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SUMMARY_FILE="${GATE_SUMMARY_FILE:-}"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  SUMMARY_FILE="$GITHUB_STEP_SUMMARY"
fi

log_summary() {
  local title="$1"
  local body="$2"
  echo ""
  echo "### ${title}"
  echo "${body}"
  if [[ -n "${SUMMARY_FILE}" ]]; then
    {
      echo "### ${title}"
      echo ""
      echo "${body}"
      echo ""
    } >> "${SUMMARY_FILE}"
  fi
}

run_step() {
  local name="$1"
  shift
  echo ""
  echo "=== GATE: ${name} ==="
  local out_file
  out_file="$(mktemp)"
  set +e
  "$@" >"${out_file}" 2>&1
  local rc=$?
  set -e
  cat "${out_file}"
  if [[ $rc -ne 0 ]]; then
    log_summary "${name}: FAILED (exit ${rc})" "\`\`\`
$(tail -n 40 "${out_file}")
\`\`\`"
    rm -f "${out_file}"
    echo "=== GATE FAILED: ${name} ==="
    exit "$rc"
  fi
  log_summary "${name}: PASSED" "\`\`\`
$(tail -n 20 "${out_file}")
\`\`\`"
  rm -f "${out_file}"
}

echo "=== Prior Auth API gates ==="
echo "cwd=${ROOT}"

run_step "ruff format check" uv run ruff format --check app tests scripts
run_step "ruff lint" uv run ruff check app tests scripts
run_step "call style (no nested calls/conditions in args)" uv run python scripts/check_call_style.py
run_step "fastapi compile + OpenAPI" uv run python scripts/check_fastapi_compile.py
run_step "postman collection fresh" uv run python scripts/check_postman_collection.py

if [[ "${GATES_SKIP_TESTS:-0}" != "1" ]]; then
  run_step "pytest + coverage" \
    uv run pytest -q --cov=app --cov-report=term-missing
fi

echo ""
echo "=== All gates passed ==="
log_summary "All gates" "All selected gates passed."
