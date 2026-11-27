#!/usr/bin/env bash
# Create the PR risk-lane labels if missing (idempotent).
set -euo pipefail

ensure() {
  local name="$1"
  local color="$2"
  local desc="$3"
  if gh label list --json name --jq '.[].name' | grep -qx "$name"; then
    echo "label ok: ${name}"
    return 0
  fi
  gh label create "$name" --color "$color" --description "$desc"
  echo "label created: ${name}"
}

ensure "low" "0E8A16" "No system behavior change (docs, .agent, tooling-only)"
ensure "medium" "FBCA04" "Backward-compatible contract change (additive response/API)"
ensure "high" "D93F0B" "Behavior/logic change in main components (may break callers)"
