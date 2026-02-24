run_with_timeout() {
  "$@"
}

run_capture() {
  local _out_var=$1
  local _dur_var=$2
  shift 2
  local tmp
  tmp=$(mktemp)
  local start_ns end_ns duration_ms
  start_ns=$(date +%s%N)
  set +e
  run_with_timeout "$@" >"$tmp" 2>&1
  local status=$?
  set -e
  end_ns=$(date +%s%N)
  duration_ms=$(python - <<'PY' "$start_ns" "$end_ns"
import sys
start=int(sys.argv[1]); end=int(sys.argv[2])
print(f"{(end - start)/1_000_000:.3f}")
PY
  )
  printf -v "$_out_var" "%s" "$(cat "$tmp")"
  printf -v "$_dur_var" "%s" "$duration_ms"
  rm -f "$tmp"
  return $status
}

warmup_only() {
  local label="$1"
  shift

  if [ "${WARMUP_REQUESTED:-0}" -le 0 ]; then
    return 0
  fi

  local out dur
  for ((i=1; i<=WARMUP_REQUESTED; i++)); do
    if ! run_capture out dur "$@"; then
      echo "[Warmup] ${label} failed." >> outputs/result.txt
      return 1
    fi
    progress_setup_tick
  done
  return 0
}

bench_capture_n() {
  local _out_var=$1
  local _times_var=$2
  local _runs=$3
  shift 3

  local out dur
  local -a times
  local out_first=""

  # Warmup runs (not included in stats/progress).
  if [ "${WARMUP:-0}" -gt 0 ]; then
    for ((i=1; i<=WARMUP; i++)); do
      if ! run_capture out dur "$@"; then
        printf -v "$_out_var" "%s" "$out"
        return 1
      fi
    done
  fi

  for ((i=1; i<=_runs; i++)); do
    if ! run_capture out dur "$@"; then
      printf -v "$_out_var" "%s" "$out"
      return 1
    fi
    if [ $i -eq 1 ]; then
      out_first="$out"
    fi
    times+=("$dur")
    progress_tick
  done

  printf -v "$_out_var" "%s" "$out_first"
  printf -v "$_times_var" "%s" "${times[*]}"
  return 0
}

run_capture_rss() {
  local _out_var=$1
  local _dur_var=$2
  local _rss_var=$3
  shift 3
  local tmp rss_tmp
  tmp=$(mktemp)
  rss_tmp=$(mktemp)
  local start_ns end_ns duration_ms rss_kb
  start_ns=$(date +%s%N)
  set +e
  if [ -x /usr/bin/time ]; then
    /usr/bin/time -f "%M" -o "$rss_tmp" "$@" >"$tmp" 2>&1
  else
    run_with_timeout "$@" >"$tmp" 2>&1
  fi
  local status=$?
  set -e
  end_ns=$(date +%s%N)
  duration_ms=$(python - <<'PY' "$start_ns" "$end_ns"
import sys
start=int(sys.argv[1]); end=int(sys.argv[2])
print(f"{(end - start)/1_000_000:.3f}")
PY
  )
  rss_kb=""
  if [ -s "$rss_tmp" ]; then
    rss_kb="$(head -n1 "$rss_tmp" | tr -d '\r' | awk '{print $1}')"
  fi
  printf -v "$_out_var" "%s" "$(cat "$tmp")"
  printf -v "$_dur_var" "%s" "$duration_ms"
  printf -v "$_rss_var" "%s" "$rss_kb"
  rm -f "$tmp" "$rss_tmp"
  return $status
}

run_capture_rss_tmp() {
  local _out_var=$1
  local _dur_var=$2
  local _rss_var=$3
  local _tmp_var=$4
  shift 4
  local tmp rss_tmp
  tmp=$(mktemp)
  rss_tmp=$(mktemp)
  local start_ns end_ns duration_ms rss_kb
  start_ns=$(date +%s%N)
  set +e
  if [ -x /usr/bin/time ]; then
    /usr/bin/time -f "%M" -o "$rss_tmp" "$@" >"$tmp" 2>&1
  else
    run_with_timeout "$@" >"$tmp" 2>&1
  fi
  local status=$?
  set -e
  end_ns=$(date +%s%N)
  duration_ms=$(python - <<'PY' "$start_ns" "$end_ns"
import sys
start=int(sys.argv[1]); end=int(sys.argv[2])
print(f"{(end - start)/1_000_000:.3f}")
PY
  )
  rss_kb=""
  if [ -s "$rss_tmp" ]; then
    rss_kb="$(head -n1 "$rss_tmp" | tr -d '\r' | awk '{print $1}')"
  fi
  printf -v "$_out_var" "%s" "$(cat "$tmp")"
  printf -v "$_dur_var" "%s" "$duration_ms"
  printf -v "$_rss_var" "%s" "$rss_kb"
  printf -v "$_tmp_var" "%s" "$tmp"
  rm -f "$rss_tmp"
  return $status
}

bench_capture_rss_n() {
  local _out_var=$1
  local _times_var=$2
  local _rss_var=$3
  local _runs=$4
  shift 4

  local out dur rss
  local -a times rsses
  local out_first=""

  # Warmup runs (not included in stats/progress).
  if [ "${WARMUP:-0}" -gt 0 ]; then
    for ((i=1; i<=WARMUP; i++)); do
      if ! run_capture_rss out dur rss "$@"; then
        printf -v "$_out_var" "%s" "$out"
        return 1
      fi
    done
  fi

  for ((i=1; i<=_runs; i++)); do
    if ! run_capture_rss out dur rss "$@"; then
      printf -v "$_out_var" "%s" "$out"
      return 1
    fi
    if [ $i -eq 1 ]; then
      out_first="$out"
    fi
    times+=("$dur")
    rsses+=("$rss")
    progress_tick
  done

  printf -v "$_out_var" "%s" "$out_first"
  printf -v "$_times_var" "%s" "${times[*]}"
  printf -v "$_rss_var" "%s" "${rsses[*]}"
  return 0
}

calc_stats_ms() {
  python - <<'PY' "$@"
import statistics
import sys

vals = []
for x in sys.argv[1:]:
    try:
        vals.append(float(x))
    except ValueError:
        pass

if not vals:
    print("")
    raise SystemExit(0)

n = len(vals)
mean = statistics.fmean(vals)
median = statistics.median(vals)
stdev = statistics.stdev(vals) if n > 1 else 0.0
print(
    f"{median:.3f} {mean:.3f} {stdev:.3f} {min(vals):.3f} {max(vals):.3f} {n}"
)
PY
}

calc_stats_kb() {
  python - <<'PY' "$@"
import statistics
import sys

vals = []
for x in sys.argv[1:]:
    try:
        vals.append(int(x))
    except ValueError:
        pass

if not vals:
    print("")
    raise SystemExit(0)

n = len(vals)
mean = statistics.fmean(vals)
median = statistics.median_low(vals)
stdev = statistics.stdev(vals) if n > 1 else 0.0
print(
    f"{median} {int(round(mean))} {int(round(stdev))} {min(vals)} {max(vals)} {n}"
)
PY
}

extract_solution_count() {
  python - <<'PY' "$1"
import re
import sys

text = sys.argv[1].replace("\r", "")
lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

# Strongest signal: explicit solution_count=... output.
m = re.search(r"solution_count\s*=\s*(-?\d+)", text, re.IGNORECASE)
if m:
    print(m.group(1))
    raise SystemExit(0)

# Next: lines that explicitly mention solutions/count.
for ln in reversed(lines):
    if "time" in ln.lower():
        continue
    m = re.search(r"\b(?:count|solution_count|solutions?)\b[^0-9-]*(-?\d+)\b", ln, re.IGNORECASE)
    if m:
        print(m.group(1))
        raise SystemExit(0)

# Common solver behavior: final non-time line is the count.
for ln in reversed(lines):
    if "time" in ln.lower():
        continue
    if re.fullmatch(r"-?\d+", ln):
        print(ln)
        raise SystemExit(0)

# Last-resort fallback: final integer on a non-time line (still avoid mapping lines).
for ln in reversed(lines):
    if "time" in ln.lower() or "mapping" in ln.lower():
        continue
    nums = re.findall(r"-?\d+", ln)
    if nums:
        print(nums[-1])
        raise SystemExit(0)

print("")
PY
}

extract_solution_times_ms() {
  python - <<'PY' "$1"
import re
import sys

text = sys.argv[1]
nums = re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", text)
if len(nums) < 3:
    print("")
    raise SystemExit(0)
try:
    sol = int(float(nums[0]))
    first_sec = float(nums[1])
    all_sec = float(nums[2])
except ValueError:
    print("")
    raise SystemExit(0)
print(f"{sol} {first_sec * 1000:.3f} {all_sec * 1000:.3f}")
PY
}

extract_count_time_ms() {
  python - <<'PY'
import re
import sys

count = None
time_ms = None
mapping_count = 0
saw_any = False

for raw in sys.stdin:
  line = raw.strip()
  if not line:
    continue
  saw_any = True
  if "Mapping:" in line:
    mapping_count += 1
    continue
  if re.search(r"\btime\b", line, re.IGNORECASE):
    nums = re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", line)
    if nums:
      try:
        time_ms = float(nums[-1])
      except ValueError:
        pass
    continue
  if re.fullmatch(r"-?\d+", line):
    try:
      count = int(line)
    except ValueError:
      pass
    continue
  m = re.search(r"\b(?:count|solution_count|solutions?)\b[^0-9-]*(-?\d+)\b", line, re.IGNORECASE)
  if m:
    try:
      count = int(m.group(1))
    except ValueError:
      pass

if not saw_any:
  # Glasgow ChatGPT prints nothing when no solution is found.
  print("0 0 0")
  raise SystemExit(0)
if count is None:
  count = mapping_count
if time_ms is None:
  # Timing for Glasgow LLMs is already captured externally; keep parser usable for count parsing.
  time_ms = 0.0
print(f"{count} {time_ms} {time_ms}")
PY
}

normalize_dijkstra_answer() {
  python - <<'PY'
import re
import sys

text = sys.stdin.read().replace("\r", "")
lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

answer = ""
for ln in lines:
    low = ln.lower()
    if low.startswith("runtime:"):
        continue
    answer = ln
    break

if not answer:
    print("")
    raise SystemExit(0)

m = re.match(r"^\s*([^;]+?)\s*;\s*(.*?)\s*$", answer)
if not m:
    print(re.sub(r"\s+", " ", answer).strip())
    raise SystemExit(0)

dist_raw = m.group(1).strip()
path_raw = m.group(2).strip()
path_low = path_raw.lower()

# Treat no-path sentinels consistently across baseline/LLM implementations.
if dist_raw.strip().lower() in {"inf", "infinity", "-1"} or "no path" in path_low:
    print("INF|")
    raise SystemExit(0)

try:
    dist_num = float(dist_raw)
    if dist_num.is_integer():
        dist_key = str(int(dist_num))
    else:
        dist_key = f"{dist_num:.12g}"
except ValueError:
    dist_key = re.sub(r"\s+", "", dist_raw).upper()

normalized_path = path_raw.replace("->", " ")
normalized_path = re.sub(r"[\[\]\(\),]", " ", normalized_path)
path_tokens = [tok for tok in normalized_path.split() if tok]

print(dist_key + "|" + ",".join(path_tokens))
PY
}

sum_ms_runs() {
  python - <<'PY' "$@"
import sys

total = 0.0
for x in sys.argv[1:]:
    try:
        total += float(x)
    except ValueError:
        pass
if sys.argv[1:]:
    print(f"{total:.3f}")
else:
    print("")
PY
}

print_stats_ms_first_all() {
  local prefix="$1"
  shift
  local indent
  indent="$(printf '%*s' ${#prefix} '')"
  printf "%s%-5s median=%10.3f mean=%10.3f stdev=%10.3f min=%10.3f max=%10.3f\n" \
    "$prefix" "first" "$1" "$2" "$3" "$4" "$5"
  printf "%s%-5s median=%10.3f mean=%10.3f stdev=%10.3f min=%10.3f max=%10.3f\n" \
    "$indent" "all" "$6" "$7" "$8" "$9" "${10}"
}

print_stats_kb_first_all() {
  local prefix="$1"
  shift
  local indent
  indent="$(printf '%*s' ${#prefix} '')"
  printf "%s%-5s median=%10d mean=%10d stdev=%10d min=%10d max=%10d\n" \
    "$prefix" "first" "$1" "$2" "$3" "$4" "$5"
  printf "%s%-5s median=%10d mean=%10d stdev=%10d min=%10d max=%10d\n" \
    "$indent" "all" "$6" "$7" "$8" "$9" "${10}"
}

t_test_line() {
  local label="$1"
  local mean1="$2"
  local stdev1="$3"
  local n1="$4"
  local mean2="$5"
  local stdev2="$6"
  local n2="$7"
  python - <<'PY' "$label" "$mean1" "$stdev1" "$n1" "$mean2" "$stdev2" "$n2"
import math
import sys

label, mean1, stdev1, n1, mean2, stdev2, n2 = sys.argv[1:]
mean1 = float(mean1)
stdev1 = float(stdev1)
n1 = float(n1)
mean2 = float(mean2)
stdev2 = float(stdev2)
n2 = float(n2)

def betacf(a, b, x):
    maxit = 200
    eps = 3.0e-10
    fpmin = 1.0e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delh = d * c
        h *= delh
        if abs(delh - 1.0) < eps:
            break
    return h

def betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * betacf(a, b, x) / a
    return 1.0 - bt * betacf(b, a, 1.0 - x) / b

def t_cdf(t, df):
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    a = df / 2.0
    b = 0.5
    ib = betai(a, b, x)
    if t >= 0:
        return 1.0 - 0.5 * ib
    return 0.5 * ib

denom = math.sqrt((stdev1 ** 2) / n1 + (stdev2 ** 2) / n2) if n1 > 0 and n2 > 0 else 0.0
if denom == 0.0:
    t_val = float("nan")
else:
    t_val = (mean1 - mean2) / denom

if n1 > 1 and n2 > 1 and denom != 0.0:
    v1 = (stdev1 ** 2) / n1
    v2 = (stdev2 ** 2) / n2
    df = (v1 + v2) ** 2 / ((v1 ** 2) / (n1 - 1.0) + (v2 ** 2) / (n2 - 1.0))
else:
    df = float("nan")

if math.isnan(df) or math.isnan(t_val):
    p_two = float("nan")
    tcrit = float("nan")
else:
    p_two = 2.0 * (1.0 - t_cdf(abs(t_val), df))
    alpha = 0.05
    target = 1.0 - alpha / 2.0
    lo, hi = 0.0, 10.0
    while t_cdf(hi, df) < target and hi < 1e6:
        hi *= 2.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < target:
            lo = mid
        else:
            hi = mid
    tcrit = (lo + hi) / 2.0

if math.isnan(tcrit):
    ci_low = float("nan")
    ci_high = float("nan")
else:
    delta = mean1 - mean2
    ci_low = delta - tcrit * denom
    ci_high = delta + tcrit * denom

print(
    f"Welch two-sample t-test ({label}): "
    f"t={t_val:.6f} df={df:.3f} p={p_two:.6g} "
    f"CI95=[{ci_low:.3f}, {ci_high:.3f}]"
)
PY
}

