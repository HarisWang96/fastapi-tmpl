#!/usr/bin/env bash

set -euo pipefail

compose=(docker compose --profile prod-sim)

cleanup() {
  result=$?
  if [[ $result -ne 0 ]]; then
    "${compose[@]}" logs --no-color --tail=100 || true
  fi
  "${compose[@]}" down
  exit "$result"
}
trap cleanup EXIT

"${compose[@]}" build prod-sim-api
"${compose[@]}" up -d --wait prod-sim-db prod-sim-redis prod-sim-rabbitmq \
  prod-sim-authz prod-sim-otel
"${compose[@]}" run --rm --no-deps prod-sim-api alembic upgrade head
"${compose[@]}" up -d --wait prod-sim-api

ready=$(curl -fsS http://localhost:18000/readyz)
for dependency in postgres redis rabbitmq; do
  grep -q "\"$dependency\":{\"status\":\"up\"" <<<"$ready"
done

test "$(curl -sS -o /dev/null -w '%{http_code}' http://localhost:18000/docs)" = 404
test "$(curl -sS -o /dev/null -w '%{http_code}' http://localhost:18000/metrics)" = 403
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  -H 'X-Metrics-Token: local-only-metrics-test-token' \
  http://localhost:18000/metrics)" = 200

identity_headers=(-H 'X-User-Id: 7' -H 'X-App-Id: local-test')
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  "${identity_headers[@]}" -H 'X-Proxy-Token: wrong-token' \
  http://localhost:18000/api/v1/demo/protected)" = 401
curl -fsS "${identity_headers[@]}" \
  -H 'X-Proxy-Token: local-only-proxy-test-token' \
  http://localhost:18000/api/v1/demo/protected | grep -q '"user_id":7'
curl -fsS "${identity_headers[@]}" \
  -H 'X-Proxy-Token: local-only-proxy-test-token' \
  http://localhost:18000/api/v1/demo/protected-scope | grep -q '"mode":"IN"'

request='{"customer_id":"prod-sim-ci","sku":"prod-sim-sku","quantity":1}'
first=$(curl -fsS -X POST http://localhost:18000/api/v1/orders \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: prod-sim-ci-order' \
  -d "$request")
second=$(curl -fsS -X POST http://localhost:18000/api/v1/orders \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: prod-sim-ci-order' \
  -d "$request")
test "$first" = "$second"

for attempt in {1..30}; do
  published=$("${compose[@]}" exec -T prod-sim-db psql -U prod_sim \
    -d fastapi_prod_sim -Atc "select count(*) from public.sys_outbox where status = 2")
  consumed=$("${compose[@]}" exec -T prod-sim-db psql -U prod_sim \
    -d fastapi_prod_sim -Atc "select count(*) from public.sys_event_consumed")
  trace_stats=$("${compose[@]}" exec -T prod-sim-otel python -c \
    "import urllib.request; print(urllib.request.urlopen('http://localhost:4318/stats').read().decode())")
  if [[ "$published" -gt 0 && "$consumed" -gt 0 ]] \
    && grep -Eq '"payload_bytes":[1-9][0-9]*' <<<"$trace_stats"; then
    break
  fi
  sleep 1
done
test "$published" -gt 0
test "$consumed" -gt 0
grep -Eq '"payload_bytes":[1-9][0-9]*' <<<"$trace_stats"
test "$("${compose[@]}" exec -T prod-sim-api id -u)" = 100

echo "Production simulation smoke test passed."
