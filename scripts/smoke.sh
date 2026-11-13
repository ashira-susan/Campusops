#!/usr/bin/env bash
# Smoke journey against a running deployment.  Usage: BASE=http://localhost:8080 SEED_PASSWORD=... ./scripts/smoke.sh
set -euo pipefail
BASE=${BASE:-http://localhost:8080}; PW=${SEED_PASSWORD:?set SEED_PASSWORD}
tok() { curl -fsS -X POST "$BASE/api/login" -H 'Content-Type: application/json' -d "{\"username\":\"$1\",\"password\":\"$PW\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])'; }
FM=$(tok fm); FAC=$(tok faculty1)
echo "health:"; curl -fsS "$BASE/api/health"; echo
SLOT=$(date +%s)                      # unique day so reruns do not collide
D=$(date -u -d "@$((SLOT))" +%Y-%m-%d)
echo "booking 1 (expect 201):"; curl -sS -o /dev/null -w "%{http_code}\n" -X POST "$BASE/api/bookings" -H "Authorization: Bearer $FAC" -H 'Content-Type: application/json' -H "Idempotency-Key: smoke-$SLOT" -d "{\"facility_id\":3,\"start_ts\":\"${D}T09:00\",\"end_ts\":\"${D}T10:00\",\"purpose\":\"smoke\"}"
echo "same booking, different key (expect 409 overlap):"; curl -sS -o /dev/null -w "%{http_code}\n" -X POST "$BASE/api/bookings" -H "Authorization: Bearer $FAC" -H 'Content-Type: application/json' -H "Idempotency-Key: smoke-b-$SLOT" -d "{\"facility_id\":3,\"start_ts\":\"${D}T09:30\",\"end_ts\":\"${D}T10:30\",\"purpose\":\"smoke\"}"
echo "sensor event (expect 201), duplicate (expect 200):"
EV="{\"sensor_id\":\"S-SMOKE\",\"event_id\":\"E-$SLOT\",\"facility_id\":1,\"metric\":\"temperature_c\",\"value\":40}"
for i in 1 2; do curl -sS -o /dev/null -w "%{http_code}\n" -X POST "$BASE/api/sensor-events" -H "Authorization: Bearer $FM" -H 'Content-Type: application/json' -d "$EV"; done
echo "dashboard:"; curl -fsS "$BASE/api/dashboard" -H "Authorization: Bearer $FM"; echo
