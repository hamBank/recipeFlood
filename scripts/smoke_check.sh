#!/usr/bin/env bash
# smoke_check.sh — post-deploy smoke check (fleet spec DEP-4). Copy to scripts/ in the app.
#
# Run by deploy.sh as the LAST step, right after the restart:
#
#   SMOKE_UNIT_PREFIX=pmoney SMOKE_DATA_PATH=/chores/ \
#     bash scripts/smoke_check.sh "http://127.0.0.1:8001" "$(git rev-parse --short HEAD)"
#   # ... and deploy.sh must exit non-zero afterwards if it failed.
#
# Usage: smoke_check.sh [BASE_URL] [EXPECTED_SHA]      (positional - NOT env vars)
#
#   BASE_URL      default http://127.0.0.1:8000
#   EXPECTED_SHA  the commit just deployed. If given, /health's backend_sha AND
#                 build_sha must both equal it (BLD-4): backend_sha proves the new
#                 code is running, build_sha proves the frontend was rebuilt from it.
#
# Settings (environment, all optional):
#   SMOKE_UNIT_PREFIX   systemd timers named "<prefix>*.timer" must be enabled and their
#                       paired .service's last Result must be "success". Skipped if unset
#                       or if systemctl isn't available.
#   SMOKE_DATA_PATH     a path (e.g. /chores/) that must answer HTTP 200 with a non-empty
#                       JSON body, i.e. the app can actually read its database.
#   SMOKE_BACKUP_GLOB   e.g. '/var/backups/app/*.sql.gz'; WARN if the newest match is
#                       older than SMOKE_BACKUP_MAX_HOURS (default 36). Skipped if unset.
#   SMOKE_CHECK_WAIT    seconds to wait for /health after a restart (default 60)
#   SMOKE_CHECK_TIMEOUT per-request timeout (default 10)
#
# Hard FAIL (exit 1): /health not 200/status ok after the wait; SHA or build mismatch;
# data path not OK; a scheduled job's last run failed. WARN only: a disabled timer, a
# stale backup. Needs only curl + python3 (+ systemctl when present).

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
EXPECTED_SHA="${2:-}"
CURL_TIMEOUT="${SMOKE_CHECK_TIMEOUT:-10}"
WAIT_SECS="${SMOKE_CHECK_WAIT:-60}"
UNIT_PREFIX="${SMOKE_UNIT_PREFIX:-}"
DATA_PATH="${SMOKE_DATA_PATH:-}"
BACKUP_GLOB="${SMOKE_BACKUP_GLOB:-}"
BACKUP_MAX_HOURS="${SMOKE_BACKUP_MAX_HOURS:-36}"
BASE_URL="${BASE_URL%/}"

FAIL=0
pass() { echo -e "\033[1;32m✓\033[0m $*"; }
fail() { echo -e "\033[1;31m✗\033[0m $*"; FAIL=1; }
warn() { echo -e "\033[1;33m⚠\033[0m $*"; }

echo "── Smoke check: $BASE_URL ──────────────────────────────"

json_field() {  # json_field <field>  (body on stdin) -> string value or empty
  python3 -c '
import sys, json
try:
    v = json.load(sys.stdin).get(sys.argv[1])
    print(v if isinstance(v, str) else "")
except Exception:
    print("")
' "$1" 2>/dev/null || true
}

# ── 0. wait for the service to come up (it was just restarted) ───────────────
WAITED=0
until [[ "$(curl -s -o /dev/null --max-time "$CURL_TIMEOUT" -w '%{http_code}' "$BASE_URL/health" 2>/dev/null || true)" == "200" ]]; do
  [[ "$WAITED" -ge "$WAIT_SECS" ]] && break
  [[ "$WAITED" -eq 0 ]] && echo "  (waiting up to ${WAIT_SECS}s for $BASE_URL/health ...)"
  sleep 2; WAITED=$((WAITED + 2))
done

# ── 1. /health ───────────────────────────────────────────────────────────────
RESP="$(curl -sS --max-time "$CURL_TIMEOUT" -w '\n%{http_code}' "$BASE_URL/health" 2>/dev/null || true)"
HEALTH_CODE=0; HEALTH_BODY=""
if [[ -n "$RESP" ]]; then
  HEALTH_CODE="$(echo "$RESP" | tail -n1)"
  HEALTH_BODY="$(echo "$RESP" | sed '$d')"
fi
if [[ "$HEALTH_CODE" != "200" ]]; then
  fail "GET /health → HTTP ${HEALTH_CODE:-no response} (expected 200)"
elif [[ "$(printf '%s' "$HEALTH_BODY" | json_field status)" == "ok" ]]; then
  pass "GET /health → HTTP 200, status=ok"
else
  fail "GET /health → HTTP 200 but status != ok (body: $HEALTH_BODY)"
fi

# ── 2. the deployed commit is what's running AND what was built ───────────────
if [[ -n "$EXPECTED_SHA" ]]; then
  if [[ "$HEALTH_CODE" != "200" ]]; then
    fail "SHA check skipped — /health did not return a usable response"
  else
    BACKEND="$(printf '%s' "$HEALTH_BODY" | json_field backend_sha)"
    BUILD="$(printf '%s' "$HEALTH_BODY" | json_field build_sha)"
    if [[ -z "$BACKEND" ]]; then
      fail "SHA check → /health has no backend_sha (is it on the fleet contract, OBS-1?)"
    elif [[ "$BACKEND" == "$EXPECTED_SHA" ]]; then
      pass "SHA check → backend $BACKEND matches expected"
    else
      fail "SHA check → backend is '$BACKEND', expected '$EXPECTED_SHA'"
    fi
    if [[ -z "$BUILD" ]]; then
      fail "Build check → /health has no build_sha: the frontend was not rebuilt (is static/version.json missing?)"
    elif [[ "$BUILD" == "$EXPECTED_SHA" ]]; then
      pass "Build check → frontend built from $BUILD, matches expected"
    else
      fail "Build check → frontend was built from '$BUILD', expected '$EXPECTED_SHA' — the build was skipped or failed and an old bundle is being served"
    fi
  fi
else
  echo "  (no EXPECTED_SHA given — skipping SHA and build checks)"
fi

# ── 3. the app can read its database ─────────────────────────────────────────
if [[ -n "$DATA_PATH" ]]; then
  RESP="$(curl -sS --max-time "$CURL_TIMEOUT" -w '\n%{http_code}' "$BASE_URL$DATA_PATH" 2>/dev/null || true)"
  CODE="$(echo "$RESP" | tail -n1)"; BODY="$(echo "$RESP" | sed '$d')"
  if [[ "$CODE" != "200" ]]; then
    fail "GET $DATA_PATH → HTTP ${CODE:-no response} (expected 200)"
  elif [[ -z "${BODY//[[:space:]]/}" || "$BODY" == "null" || "$BODY" == "[]" || "$BODY" == "{}" ]]; then
    fail "GET $DATA_PATH → HTTP 200 but the body is empty"
  else
    pass "GET $DATA_PATH → HTTP 200, non-empty"
  fi
fi

# ── 4. scheduled jobs (systemd timers) ───────────────────────────────────────
if [[ -z "$UNIT_PREFIX" ]]; then
  echo "  (SMOKE_UNIT_PREFIX not set — skipping scheduled-job checks)"
elif ! command -v systemctl &>/dev/null; then
  echo "  (systemctl not available — skipping scheduled-job checks; expected off the server)"
else
  FOUND=0
  while read -r TIMER _; do
    [[ -z "$TIMER" ]] && continue
    FOUND=1
    SERVICE="${TIMER%.timer}.service"
    ENABLED="$(systemctl is-enabled "$TIMER" 2>/dev/null || true)"
    RESULT="$(systemctl show "$SERVICE" --property=Result --value 2>/dev/null || true)"
    if [[ "$ENABLED" != "enabled" ]]; then
      warn "$TIMER is '$ENABLED', not enabled — it will never run. Fix: sudo systemctl enable --now $TIMER"
    elif [[ -n "$RESULT" && "$RESULT" != "success" ]]; then
      # systemd reports a non-zero exit as "exit-code", not "failed".
      fail "$SERVICE's last run failed (Result=$RESULT) — check: journalctl -u $SERVICE -n 40; re-run: sudo systemctl start $SERVICE"
    else
      pass "$TIMER enabled, $SERVICE last result: ${RESULT:-not yet run}"
    fi
  done < <(systemctl list-unit-files "${UNIT_PREFIX}*.timer" --no-legend 2>/dev/null || true)
  [[ "$FOUND" -eq 0 ]] && warn "no systemd timers match '${UNIT_PREFIX}*.timer' — are scheduled jobs installed?"
fi

# ── 5. backup freshness ──────────────────────────────────────────────────────
if [[ -n "$BACKUP_GLOB" ]]; then
  # shellcheck disable=SC2086
  NEWEST="$(ls -1t $BACKUP_GLOB 2>/dev/null | head -1 || true)"
  if [[ -z "$NEWEST" ]]; then
    warn "no backup found matching $BACKUP_GLOB — has the backup job ever run?"
  else
    AGE_H=$(( ( $(date +%s) - $(date -r "$NEWEST" +%s 2>/dev/null || echo 0) ) / 3600 ))
    if [[ "$AGE_H" -gt "$BACKUP_MAX_HOURS" ]]; then
      warn "newest backup ($NEWEST) is ${AGE_H}h old — expected within ~24h"
    else
      pass "newest backup: $NEWEST (${AGE_H}h old)"
    fi
  fi
fi

echo "──────────────────────────────────────────────────────────"
if [[ "$FAIL" -eq 0 ]]; then pass "Smoke check passed"; exit 0; else fail "Smoke check FAILED"; exit 1; fi
