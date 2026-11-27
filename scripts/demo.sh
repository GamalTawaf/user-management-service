#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BASE_URL="${BASE_URL:-http://localhost:8000}"
MAILDEV_URL="${MAILDEV_URL:-http://localhost:1080}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://prior:prior@localhost:5432/prior_auth}"
export JWT_SECRET="${JWT_SECRET:-dev-only-change-me-32bytes-min!!}"

echo "== migrate =="
uv run alembic upgrade head

echo "== seed =="
uv run python scripts/seed.py | tee /tmp/prior-auth-seed.out
eval "$(python3 - <<'PY'
from pathlib import Path
text = Path("/tmp/prior-auth-seed.out").read_text()
roles = ("office", "reviewer_coi", "reviewer", "admin", "auditor", "member")
for line in text.splitlines():
    line = line.strip()
    for role in roles:
        prefix = f"{role}:"
        if line.startswith(prefix):
            token = line[len(prefix) :].strip()
            print(f"export {role.upper()}_TOKEN={token!r}")
            break
PY
)"

echo "== health =="
curl -sf "$BASE_URL/v1/health"
echo

TODAY=$(uv run python -c 'from app.clock import get_today; print(get_today().isoformat())')
MEMBER_ID=22222222-2222-2222-2222-222222222222
UNLINKED=22222222-2222-2222-2222-222222222299
IDEM_KEY="demo-idem-$(date +%s)"

echo "== 1) submit fail (unlinked) =="
FAIL=$(curl -s -X POST "$BASE_URL/v1/prior-auths" \
  -H "Authorization: Bearer $OFFICE_TOKEN" -H "Content-Type: application/json" \
  -d "{\"member_id\":\"$UNLINKED\",\"diagnosis_icd10\":\"J06.9\",\"date_of_service\":\"$TODAY\",\"clinical_note\":\"n\",\"procedures\":[{\"code\":\"99213\",\"units\":1}]}")
echo "$FAIL"
CID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['correlation_id'])" "$FAIL")

echo "== 2) support lookup =="
curl -sf -H "Authorization: Bearer $OFFICE_TOKEN" \
  "$BASE_URL/v1/support/intake-rejections/$CID"
echo

SUBMIT_BODY="{\"member_id\":\"$MEMBER_ID\",\"diagnosis_icd10\":\"J06.9\",\"date_of_service\":\"$TODAY\",\"clinical_note\":\"SECRET\",\"procedures\":[{\"code\":\"99213\",\"units\":1}]}"

echo "== 3) submit ok (Idempotency-Key) =="
OK=$(curl -s -X POST "$BASE_URL/v1/prior-auths" \
  -H "Authorization: Bearer $OFFICE_TOKEN" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $IDEM_KEY" \
  -d "$SUBMIT_BODY")
echo "$OK"
RID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['uuid'])" "$OK")

echo "== 4) Idempotency-Key replay (same key+body → same id) =="
REPLAY=$(curl -s -X POST "$BASE_URL/v1/prior-auths" \
  -H "Authorization: Bearer $OFFICE_TOKEN" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $IDEM_KEY" \
  -d "$SUBMIT_BODY")
echo "$REPLAY"
python3 -c "import json,sys; a=json.loads(sys.argv[1]); b=json.loads(sys.argv[2]); assert a['uuid']==b['uuid'], (a['uuid'], b['uuid']); print('idempotency replay OK', a['uuid'])" "$OK" "$REPLAY"

echo "== 5) claim =="
CLAIM=$(curl -sf -X POST -H "Authorization: Bearer $REVIEWER_TOKEN" \
  "$BASE_URL/v1/prior-auths/$RID/claim")
echo "$CLAIM"
echo "(second claim should 409)"
curl -s -o /dev/null -w "second_claim=%{http_code}\n" -X POST \
  -H "Authorization: Bearer $REVIEWER_TOKEN" \
  "$BASE_URL/v1/prior-auths/$RID/claim" || true

echo "== 6) workload (ops_admin) =="
curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$BASE_URL/v1/reviewers/workload"
echo

echo "== 7) COI claim =="
OK2=$(curl -s -X POST "$BASE_URL/v1/prior-auths" \
  -H "Authorization: Bearer $OFFICE_TOKEN" -H "Content-Type: application/json" \
  -d "{\"member_id\":\"$MEMBER_ID\",\"diagnosis_icd10\":\"J06.9\",\"date_of_service\":\"$TODAY\",\"procedures\":[{\"code\":\"99214\",\"units\":1}]}")
RID2=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['uuid'])" "$OK2")
curl -s -o /dev/null -w "coi_claim=%{http_code}\n" -X POST \
  -H "Authorization: Bearer $REVIEWER_COI_TOKEN" \
  "$BASE_URL/v1/prior-auths/$RID2/claim"

echo "== 8) decide =="
PROC=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['procedures'][0]['uuid'])" "$CLAIM")
DECIDE=$(curl -sf -X POST -H "Authorization: Bearer $REVIEWER_TOKEN" -H "Content-Type: application/json" \
  -d "{\"outcomes\":[{\"procedure_id\":\"$PROC\",\"decision\":\"denied\",\"denial_reason\":\"Not medically necessary\"}]}" \
  "$BASE_URL/v1/prior-auths/$RID/decision")
echo "$DECIDE"

echo "== 9) MailDev (decision notice) =="
MAILDEV_OK=0
if curl -sf -o /dev/null "$MAILDEV_URL/"; then
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    EMAILS=$(curl -sf "$MAILDEV_URL/email" || echo "[]")
    HIT=$(python3 -c "import json,sys; rid=sys.argv[1]; emails=json.loads(sys.argv[2]); print(any(rid in json.dumps(e) for e in emails))" "$RID" "$EMAILS")
    if [[ "$HIT" == "True" ]]; then
      echo "MailDev has decision notice for $RID"
      MAILDEV_OK=1
      break
    fi
    sleep 1
  done
  if [[ "$MAILDEV_OK" -ne 1 ]]; then
    echo "NOTE: MailDev up but no message yet — check UI $MAILDEV_URL (outbox-worker must be running)"
  fi
else
  echo "NOTE: MailDev not reachable at $MAILDEV_URL — start compose (maildev + outbox-worker) and open UI"
fi

echo "== 10) auditor audit GET =="
AUDIT=$(curl -sf -H "Authorization: Bearer $AUDITOR_TOKEN" \
  "$BASE_URL/v1/prior-auths/$RID/audit")
echo "$AUDIT"
python3 -c "import json,sys; ev=json.loads(sys.argv[1]); assert any(e.get('action')=='decide' for e in ev), ev; print('auditor audit OK')" "$AUDIT"

echo "== 11) member redaction =="
MEM=$(curl -sf -H "Authorization: Bearer $MEMBER_TOKEN" \
  "$BASE_URL/v1/me/prior-auths/$RID")
echo "$MEM"
python3 -c "import json,sys; b=json.loads(sys.argv[1]); assert 'clinical_note' not in b; assert 'denial_reason' not in json.dumps(b); assert b['procedures'][0]['status']=='not_approved'; print('member redaction OK')" "$MEM"

echo "Demo complete."
