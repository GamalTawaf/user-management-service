#!/usr/bin/env bash
# Live walkthrough for the user-management API.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export JWT_SECRET="${JWT_SECRET:-dev-only-change-me-32bytes-min!!}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://ums:ums@localhost:5433/user_mgmt}"

echo "=== wait for API health ==="
for _ in $(seq 1 60); do
  if curl -sf localhost:8000/v1/health >/dev/null; then
    break
  fi
  sleep 1
done
curl -sf localhost:8000/v1/health >/dev/null

echo "=== seed ==="
SEED_OUT="$(uv run python scripts/seed.py)"
echo "$SEED_OUT"
ADMIN_TOKEN="$(echo "$SEED_OUT" | awk '/^  admin:/{print $2}')"
MEMBER_TOKEN="$(echo "$SEED_OUT" | awk '/^  member:/{print $2}')"
AUDITOR_TOKEN="$(echo "$SEED_OUT" | awk '/^  auditor:/{print $2}')"
ORG_ID="$(echo "$SEED_OUT" | awk -F= '/^org_id=/{print $2}')"
INVITED_ID="$(echo "$SEED_OUT" | awk -F= '/^invited_id=/{print $2}')"

echo "=== me ==="
curl -sf -H "Authorization: Bearer $MEMBER_TOKEN" localhost:8000/v1/me | tee /tmp/ums_me.json
echo

echo "=== create user ==="
CREATE=$(curl -sf -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" -H "Idempotency-Key: demo-create-1" \
  -d "{\"email\":\"demo.user@example.com\",\"display_name\":\"Demo User\",\"role\":\"member\",\"status\":\"invited\",\"org_id\":\"$ORG_ID\"}" \
  localhost:8000/v1/users)
echo "$CREATE"
USER_ID=$(echo "$CREATE" | python -c 'import sys,json; print(json.load(sys.stdin)["uuid"])')

echo "=== idempotency replay ==="
REPLAY=$(curl -sf -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" -H "Idempotency-Key: demo-create-1" \
  -d "{\"email\":\"demo.user@example.com\",\"display_name\":\"Demo User\",\"role\":\"member\",\"status\":\"invited\",\"org_id\":\"$ORG_ID\"}" \
  localhost:8000/v1/users)
echo "$REPLAY" | python -c 'import sys,json; b=json.load(sys.stdin); assert b["uuid"]'
echo "idempotency replay OK"

echo "=== activate ==="
curl -sf -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "localhost:8000/v1/users/$USER_ID/activate" | tee /tmp/ums_activate.json
echo

echo "=== stats ==="
curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/v1/users/stats
echo

echo "=== activate seeded invited ==="
curl -sf -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "localhost:8000/v1/users/$INVITED_ID/activate" >/dev/null
echo "invited activated"

echo "=== disable / enable ==="
curl -sf -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "localhost:8000/v1/users/$USER_ID/disable" >/dev/null
curl -sf -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "localhost:8000/v1/users/$USER_ID/enable" >/dev/null
echo "disable/enable OK"

echo "=== audit ==="
curl -sf -H "Authorization: Bearer $AUDITOR_TOKEN" \
  "localhost:8000/v1/users/$USER_ID/audit" | tee /tmp/ums_audit.json
echo

echo "=== MailDev (welcome email) ==="
sleep 3
curl -sf http://localhost:1080/email | python -c 'import sys,json; m=json.load(sys.stdin); print("messages", len(m))'
echo
echo "Grafana LGTM: http://localhost:3000  (OTLP traces/logs/metrics)"
echo "demo complete"
