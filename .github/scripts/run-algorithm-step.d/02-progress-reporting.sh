# Progress reporting via GitHub Checks API (used by the web UI progress bar).
PROGRESS_ENABLED=0
CHECK_RUN_ID=""
CHECK_RUN_NAME="Capstone Benchmark Progress (${REQUEST_ID:-${GITHUB_RUN_ID}})"
PROGRESS_STAGE="setup"
PROGRESS_SETUP_TOTAL=0
PROGRESS_SETUP_DONE=0
PROGRESS_TOTAL_UNITS=0
PROGRESS_TOTAL_TICKS=0
PROGRESS_DONE_TICKS=0
PROGRESS_PHASE=""
PROGRESS_LAST_UPDATE_EPOCH=0
PROGRESS_LAST_REPORTED_SETUP=-1
PROGRESS_LAST_REPORTED_TICKS=-1

# Progress semantics: count "per program per iteration".
# For Glasgow and VF3, both "first" and "all" runs are counted together as 1 unit.
UNITS_PER_ITER=0
TICKS_PER_ITER=0
TICKS_PER_UNIT=1
case "$ALGORITHM" in
  dijkstra)
    UNITS_PER_ITER=3   # baseline + gemini + chatgpt
    TICKS_PER_ITER=3   # all are directly ticked
    ;;
  glasgow)
    UNITS_PER_ITER=3   # baseline + gemini + chatgpt
    TICKS_PER_ITER=6   # each has first + all (each ticks)
    ;;
  vf3)
    UNITS_PER_ITER=3   # baseline + gemini + chatgpt
    TICKS_PER_ITER=3   # each runs once (reports first + all)
    ;;
  subgraph)
    UNITS_PER_ITER=6   # vf3 baseline/chatgpt/gemini + glasgow baseline/chatgpt/gemini
    TICKS_PER_ITER=9   # vf3 (3) + glasgow (6: first+all)
    ;;
  *)
    UNITS_PER_ITER=0
    TICKS_PER_ITER=0
    ;;
esac
if [ "$UNITS_PER_ITER" -gt 0 ] && [ "$TICKS_PER_ITER" -gt 0 ]; then
  TICKS_PER_UNIT=$((TICKS_PER_ITER / UNITS_PER_ITER))
fi
PROGRESS_TOTAL_UNITS=$((ITERATIONS * UNITS_PER_ITER))
PROGRESS_TOTAL_TICKS=$((ITERATIONS * TICKS_PER_ITER))
PROGRESS_SETUP_TOTAL=$((WARMUP_REQUESTED * TICKS_PER_ITER))
if [ "$PROGRESS_SETUP_TOTAL" -le 0 ]; then
  PROGRESS_SETUP_TOTAL=1
fi

progress_create_check_run() {
  if [ -z "${GITHUB_TOKEN:-}" ] || [ "$PROGRESS_TOTAL_UNITS" -le 0 ] || [ "$PROGRESS_TOTAL_TICKS" -le 0 ]; then
    return 0
  fi

  CHECK_RUN_ID="$(
    python - <<'PY' "$CHECK_RUN_NAME" "$REQUEST_ID" "$ALGORITHM" "$ITERATIONS" "$UNITS_PER_ITER" "$TICKS_PER_UNIT" "$PROGRESS_TOTAL_UNITS" "$PROGRESS_TOTAL_TICKS" "$PROGRESS_STAGE" "$PROGRESS_SETUP_DONE" "$PROGRESS_SETUP_TOTAL" || true
import datetime
import json
import os
import sys
import urllib.request

name = sys.argv[1]
request_id = sys.argv[2]
algorithm = sys.argv[3]
iterations = int(sys.argv[4])
units_per_iter = int(sys.argv[5])
ticks_per_unit = int(sys.argv[6])
total_units = int(sys.argv[7])
total_ticks = int(sys.argv[8])
stage = sys.argv[9] if len(sys.argv) > 9 else "tests"
setup_done = int(sys.argv[10]) if len(sys.argv) > 10 else 0
setup_total = int(sys.argv[11]) if len(sys.argv) > 11 else 0

token = os.environ.get("GITHUB_TOKEN", "")
repo = os.environ.get("GITHUB_REPOSITORY", "")
sha = os.environ.get("GITHUB_SHA", "")
if not token or not repo or not sha:
    print("")
    raise SystemExit(0)

url = f"https://api.github.com/repos/{repo}/check-runs"
headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {token}",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "capstone-algorithm-runner",
}
progress = {
    "request_id": request_id,
    "algorithm": algorithm,
    "iterations": iterations,
    "tests_per_iteration": units_per_iter,
    "ticks_per_unit": ticks_per_unit,
    "total_ticks": total_ticks,
    "completed": 0,
    "total": total_units,
    "percent": 0.0,
    "phase": "",
    "run_id": os.environ.get("GITHUB_RUN_ID", ""),
    "stage": stage,
    "setup_completed": setup_done,
    "setup_total": setup_total,
    "tests_completed": 0,
    "tests_total": total_units,
}

setup_percent = (setup_done / setup_total * 100.0) if setup_total else 0.0
summary = f"Progress: 0/{total_units} (0.0%)"
if stage == "setup":
    summary = f"Setup: {setup_done}/{setup_total} ({setup_percent:.1f}%)"
payload = {
    "name": name,
    "head_sha": sha,
    "status": "in_progress",
    "started_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "output": {
        "title": name,
        "summary": summary,
        "text": json.dumps(progress),
    },
}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers=headers,
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    print(data.get("id", ""))
except Exception:
    print("")
PY
  )"

  if [[ "$CHECK_RUN_ID" =~ ^[0-9]+$ ]]; then
    PROGRESS_ENABLED=1
    PROGRESS_LAST_UPDATE_EPOCH=$(date +%s)
    PROGRESS_LAST_REPORTED_SETUP=0
    PROGRESS_LAST_REPORTED_TICKS=0
  fi
  return 0
}

progress_update_check_run() {
  local status="$1"
  local conclusion="${2:-}"
  if [ "${PROGRESS_ENABLED:-0}" != "1" ] || [ -z "${CHECK_RUN_ID:-}" ]; then
    return 0
  fi

  python - <<'PY' "$CHECK_RUN_ID" "$CHECK_RUN_NAME" "$REQUEST_ID" "$ALGORITHM" "$ITERATIONS" "$UNITS_PER_ITER" "$TICKS_PER_UNIT" "$PROGRESS_DONE_TICKS" "$PROGRESS_TOTAL_TICKS" "$PROGRESS_TOTAL_UNITS" "$PROGRESS_STAGE" "$PROGRESS_SETUP_DONE" "$PROGRESS_SETUP_TOTAL" "$PROGRESS_PHASE" "$status" "$conclusion" || true
import datetime
import json
import os
import sys
import urllib.request

check_id = sys.argv[1]
name = sys.argv[2]
request_id = sys.argv[3]
algorithm = sys.argv[4]
iterations = int(sys.argv[5])
units_per_iter = int(sys.argv[6])
ticks_per_unit = int(sys.argv[7])
completed_ticks = int(sys.argv[8])
total_ticks = int(sys.argv[9])
total_units = int(sys.argv[10])
stage = sys.argv[11] if len(sys.argv) > 11 else "tests"
setup_done = int(sys.argv[12]) if len(sys.argv) > 12 else 0
setup_total = int(sys.argv[13]) if len(sys.argv) > 13 else 0
phase = sys.argv[14] if len(sys.argv) > 14 else ""
status = sys.argv[15] if len(sys.argv) > 15 else "in_progress"
conclusion = sys.argv[16] if len(sys.argv) > 16 else ""

token = os.environ.get("GITHUB_TOKEN", "")
repo = os.environ.get("GITHUB_REPOSITORY", "")
if not token or not repo:
    raise SystemExit(0)

completed_units = (completed_ticks / ticks_per_unit) if ticks_per_unit else 0.0
percent = (completed_ticks / total_ticks * 100.0) if total_ticks else 0.0
progress = {
    "request_id": request_id,
    "algorithm": algorithm,
    "iterations": iterations,
    "tests_per_iteration": units_per_iter,
    "ticks_per_unit": ticks_per_unit,
    "completed": round(completed_units, 3),
    "total": total_units,
    "total_ticks": total_ticks,
    "percent": round(percent, 3),
    "phase": phase,
    "run_id": os.environ.get("GITHUB_RUN_ID", ""),
    "stage": stage,
    "setup_completed": setup_done,
    "setup_total": setup_total,
    "tests_completed": round(completed_units, 3),
    "tests_total": total_units,
}

if ticks_per_unit > 1:
    completed_str = f"{completed_units:.1f}"
else:
    completed_str = str(int(completed_units))

setup_percent = (setup_done / setup_total * 100.0) if setup_total else 0.0
if stage == "setup":
    summary = f"Setup: {setup_done}/{setup_total} ({setup_percent:.1f}%)"
else:
    summary = f"Progress: {completed_str}/{total_units} ({percent:.1f}%)"
if phase:
    summary += f"\\nPhase: {phase}"

payload = {
    "status": status,
    "output": {
        "title": name,
        "summary": summary,
        "text": json.dumps(progress),
    },
}
if status == "completed":
    payload["completed_at"] = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    if conclusion:
        payload["conclusion"] = conclusion

url = f"https://api.github.com/repos/{repo}/check-runs/{check_id}"
headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {token}",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "capstone-algorithm-runner",
}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers=headers,
    method="PATCH",
)
try:
    with urllib.request.urlopen(req, timeout=10):
        pass
except Exception:
    pass
PY

  PROGRESS_LAST_UPDATE_EPOCH=$(date +%s)
  if [ "${PROGRESS_STAGE:-tests}" = "setup" ]; then
    PROGRESS_LAST_REPORTED_SETUP="$PROGRESS_SETUP_DONE"
  else
    PROGRESS_LAST_REPORTED_TICKS="$PROGRESS_DONE_TICKS"
  fi
  return 0
}

progress_maybe_update() {
  if [ "${PROGRESS_ENABLED:-0}" != "1" ]; then
    return 0
  fi

  local now_epoch
  now_epoch=$(date +%s)

  local stage current total last
  stage="${PROGRESS_STAGE:-tests}"
  if [ "$stage" = "setup" ]; then
    current="${PROGRESS_SETUP_DONE:-0}"
    total="${PROGRESS_SETUP_TOTAL:-0}"
    last="${PROGRESS_LAST_REPORTED_SETUP--1}"
  else
    current="${PROGRESS_DONE_TICKS:-0}"
    total="${PROGRESS_TOTAL_TICKS:-0}"
    last="${PROGRESS_LAST_REPORTED_TICKS--1}"
  fi

  if [ "${total:-0}" -le 0 ]; then
    progress_update_check_run "in_progress"
    return 0
  fi

  if [ "$current" -ge "$total" ]; then
    progress_update_check_run "in_progress"
    return 0
  fi

  if [ "$current" -le 2 ]; then
    progress_update_check_run "in_progress"
    return 0
  fi

  if [ "$current" -ne "$last" ] && [ $((now_epoch - PROGRESS_LAST_UPDATE_EPOCH)) -ge 5 ]; then
    progress_update_check_run "in_progress"
  fi
  return 0
}

progress_set_phase() {
  PROGRESS_PHASE="$1"
  progress_maybe_update
}

progress_tick() {
  PROGRESS_DONE_TICKS=$((PROGRESS_DONE_TICKS + 1))
  progress_maybe_update
}

progress_setup_tick() {
  PROGRESS_SETUP_DONE=$((PROGRESS_SETUP_DONE + 1))
  if [ "$PROGRESS_SETUP_DONE" -gt "$PROGRESS_SETUP_TOTAL" ]; then
    PROGRESS_SETUP_DONE="$PROGRESS_SETUP_TOTAL"
  fi
  progress_maybe_update
}

progress_finish() {
  if [ "${PROGRESS_ENABLED:-0}" != "1" ] || [ -z "${CHECK_RUN_ID:-}" ]; then
    return 0
  fi
  PROGRESS_DONE_TICKS="$PROGRESS_TOTAL_TICKS"
  local conclusion="success"
  if [ "${EXIT_CODE:-0}" != "0" ]; then
    conclusion="failure"
  fi
  progress_update_check_run "completed" "$conclusion"
  return 0
}

progress_create_check_run
trap 'rc=$?; if [ -z "${EXIT_CODE:-}" ]; then EXIT_CODE=$rc; fi; progress_finish || true' EXIT

