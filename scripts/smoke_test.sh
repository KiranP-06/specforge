#!/usr/bin/env bash
# Post-deploy smoke tests (app, API, monitoring). Usage: scripts/smoke_test.sh <base-url> [expected-git-sha]
# Set SKIP_GRAFANA=1 for docker-compose without the monitoring profile.
set -euo pipefail
BASE="${1:-http://127.0.0.1}"
EXPECTED_SHA="${2:-}"
fail=0

check() {  # name, url, expected status, optional grep pattern
  local name=$1 url=$2 want=$3 pattern=${4:-}
  local body status
  body=$(mktemp)
  for _ in 1 2 3 4 5 6; do
    status=$(curl -s -o "$body" -w '%{http_code}' --max-time 10 "$url" || echo 000)
    [ "$status" = "$want" ] && break
    sleep 5
  done
  if [ "$status" != "$want" ]; then echo "✗ $name → HTTP $status (want $want)"; fail=1
  elif [ -n "$pattern" ] && ! grep -q "$pattern" "$body"; then echo "✗ $name → body missing '$pattern'"; fail=1
  else echo "✓ $name"; fi
  rm -f "$body"
}

check "web index"        "$BASE/"              200 "SPECForge"
check "api liveness"     "$BASE/health"        200 '"status":"ok"'
check "api readiness"    "$BASE/ready"         200 '"database":"ok"'
check "api metadata"     "$BASE/api/meta"      200 '"app":"SPECForge"'
check "openapi schema"   "$BASE/openapi.json"  200 '"SPECForge API"'
check "auth enforced"    "$BASE/api/projects"  401
[ -z "${SKIP_GRAFANA:-}" ] && check "grafana"          "$BASE/grafana/api/health" 200 '"database"'
[ -n "$EXPECTED_SHA" ] && check "running new build" "$BASE/health" 200 "$EXPECTED_SHA"

exit $fail
