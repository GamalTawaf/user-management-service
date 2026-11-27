#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/.git/hooks/pre-commit"
mkdir -p "$ROOT/.git/hooks"
cat > "$HOOK" << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export GATES_SKIP_TESTS="${GATES_SKIP_TESTS:-0}"
# Fast commit gate: lint + call-style + fastapi compile. Full pytest is CI / init.sh.
export GATES_SKIP_TESTS=1
exec ./scripts/gates.sh
EOF
chmod +x "$HOOK"
echo "Installed pre-commit hook -> $HOOK"
echo "Runs: ruff format/check, call-style, fastapi compile, postman fresh (skip pytest; CI runs full suite)"
