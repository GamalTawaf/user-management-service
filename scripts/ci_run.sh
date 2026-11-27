#!/usr/bin/env bash
# Run a CI step, tee output, and append a PASS/FAIL block to $GITHUB_STEP_SUMMARY.
# Usage: ./scripts/ci_run.sh "step title" [--tail N] -- command [args...]
set -euo pipefail

title=""
tail_n=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tail)
      tail_n="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      if [[ -z "$title" ]]; then
        title="$1"
        shift
      else
        echo "usage: $0 \"title\" [--tail N] -- command..." >&2
        exit 2
      fi
      ;;
  esac
done

if [[ -z "$title" || $# -lt 1 ]]; then
  echo "usage: $0 \"title\" [--tail N] -- command..." >&2
  exit 2
fi

out="$(mktemp)"
trap 'rm -f "$out"' EXIT

set +e
set -o pipefail
"$@" 2>&1 | tee "$out"
rc=${PIPESTATUS[0]}
set -e

body_file="$(mktemp)"
trap 'rm -f "$out" "$body_file"' EXIT
if [[ "$tail_n" -gt 0 ]]; then
  tail -n "$tail_n" "$out" >"$body_file"
else
  cat "$out" >"$body_file"
fi

{
  if [[ "$rc" -eq 0 ]]; then
    echo "### ${title}: PASSED"
  else
    echo "### ${title}: FAILED"
  fi
  echo ""
  echo '```'
  cat "$body_file"
  echo '```'
  echo ""
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

exit "$rc"
