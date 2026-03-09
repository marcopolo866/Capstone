set -uo pipefail

if ! command -v python >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    python() { python3 "$@"; }
  else
    echo "Python is required but neither 'python' nor 'python3' was found." >&2
    exit 1
  fi
fi

ALGORITHM="${ALGORITHM_INPUT:-}"
SUBGRAPH_PHASE="${SUBGRAPH_PHASE_INPUT:-}"
ITERATIONS_RAW="${ITERATIONS_INPUT:-1}"
WARMUP_RAW="${WARMUP_INPUT:-1}"
INPUT_MODE="${INPUT_MODE_INPUT:-premade}"
GENERATOR_N="${GENERATOR_N_INPUT:-}"
GENERATOR_K="${GENERATOR_K_INPUT:-}"
GENERATOR_DENSITY="${GENERATOR_DENSITY_INPUT:-0.05}"
GENERATOR_SEED_RAW="${GENERATOR_SEED_INPUT:-}"
INPUT_FILES="${INPUT_FILES_INPUT:-}"
REQUEST_ID="${REQUEST_ID_INPUT:-}"

mkdir -p outputs
: > outputs/result.txt
RUN_STARTED_NS="$(date +%s%N)"
GEN_COUNTER=0
SOLVER_TIME_MS_TOTAL=""
SEED_USED=""
VIS_SEED=""
EQUIVALENCE_REPORT_FILE="outputs/equivalence_report.jsonl"
if [ "$ALGORITHM" != "subgraph" ] || [ "${SUBGRAPH_PHASE:-}" != "glasgow" ]; then
  : > "$EQUIVALENCE_REPORT_FILE"
elif [ ! -f "$EQUIVALENCE_REPORT_FILE" ]; then
  : > "$EQUIVALENCE_REPORT_FILE"
fi

check_subgraph_equivalence_json() {
  local lad_pattern="$1"
  local lad_target="$2"
  local vf_pattern="$3"
  local vf_target="$4"
  python - "$lad_pattern" "$lad_target" "$vf_pattern" "$vf_target" <<'PY'
import json
import re
import sys
from pathlib import Path

lad_pattern = Path(sys.argv[1])
lad_target = Path(sys.argv[2])
vf_pattern = Path(sys.argv[3])
vf_target = Path(sys.argv[4])

def parse_lad(path: Path):
    lines = path.read_text(encoding="utf-8", errors="ignore").replace("\r", "").splitlines()
    idx = 0
    def next_line():
        nonlocal idx
        while idx < len(lines):
            line = lines[idx].strip()
            idx += 1
            if not line or line.startswith("#"):
                continue
            return line
        return None
    first = next_line()
    if first is None:
        return {"adj": [], "labels": []}
    n = int(first)
    adj = [set() for _ in range(max(0, n))]
    labels = [0 for _ in range(max(0, n))]
    for i in range(n):
        line = next_line()
        if line is None:
            break
        vals = []
        for tok in line.split():
            try:
                vals.append(int(tok))
            except ValueError:
                pass
        if not vals:
            continue
        degree = vals[0]
        start = 1
        if len(vals) >= 2 and vals[1] == (len(vals) - 2):
            labels[i] = vals[0]
            degree = vals[1]
            start = 2
        if degree < 0:
            degree = 0
        for j in range(degree):
            pos = start + j
            if pos >= len(vals):
                break
            v = vals[pos]
            if 0 <= v < n and v != i:
                adj[i].add(v)
                adj[v].add(i)
    return {"adj": [sorted(list(s)) for s in adj], "labels": labels}

def parse_vf(path: Path):
    lines = path.read_text(encoding="utf-8", errors="ignore").replace("\r", "").splitlines()
    idx = 0
    def next_nums():
        nonlocal idx
        while idx < len(lines):
            line = lines[idx]
            idx += 1
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            nums = [int(x) for x in re.findall(r"-?\d+", line)]
            if nums:
                return nums
        return None

    header = next_nums()
    if not header:
        return {"adj": [], "labels": []}
    n = max(0, int(header[0]))
    labels = [0 for _ in range(n)]
    for i in range(n):
        row = next_nums()
        if row is None:
            break
        if len(row) >= 2:
            labels[i] = int(row[1])
    adj = [set() for _ in range(n)]
    for i in range(n):
        count_line = next_nums()
        if not count_line:
            break
        m = max(0, int(count_line[0]))
        for _ in range(m):
            edge = next_nums()
            if not edge:
                break
            j = None
            if len(edge) >= 2:
                a, b = int(edge[0]), int(edge[1])
                if a == i and 0 <= b < n:
                    j = b
                elif b == i and 0 <= a < n:
                    j = a
                elif 0 <= a < n:
                    j = a
                elif 0 <= b < n:
                    j = b
            else:
                a = int(edge[0])
                if 0 <= a < n:
                    j = a
            if j is None or j == i:
                continue
            adj[i].add(j)
            adj[j].add(i)
    return {"adj": [sorted(list(s)) for s in adj], "labels": labels}

def edge_set(adj):
    out = set()
    for i, nbrs in enumerate(adj):
        for j in nbrs:
            if i == j:
                continue
            a, b = (i, j) if i < j else (j, i)
            out.add((a, b))
    return out

def compare_graph(vf_graph, lad_graph, name):
    vf_adj = vf_graph.get("adj", [])
    lad_adj = lad_graph.get("adj", [])
    vf_labels = vf_graph.get("labels", [])
    lad_labels = lad_graph.get("labels", [])
    n_vf = len(vf_adj)
    n_lad = len(lad_adj)
    n = min(n_vf, n_lad)
    label_mismatches = []
    for i in range(n):
        lvf = int(vf_labels[i]) if i < len(vf_labels) else 0
        lld = int(lad_labels[i]) if i < len(lad_labels) else 0
        if lvf != lld:
            label_mismatches.append({"node": i, "vf_label": lvf, "lad_label": lld})
    vf_edges = edge_set(vf_adj)
    lad_edges = edge_set(lad_adj)
    missing_edges = sorted(list(vf_edges - lad_edges))
    extra_edges = sorted(list(lad_edges - vf_edges))
    # Equivalence for this pipeline is adjacency-only (labels are informational).
    equivalent = (n_vf == n_lad) and not missing_edges and not extra_edges
    return {
        "graph": name,
        "equivalent": equivalent,
        "node_count_vf": n_vf,
        "node_count_lad": n_lad,
        "label_compare_ignored": True,
        "label_mismatch_count": len(label_mismatches),
        "label_mismatch_samples": label_mismatches[:10],
        "missing_edges_count": len(missing_edges),
        "missing_edge_samples": [list(e) for e in missing_edges[:10]],
        "extra_edges_count": len(extra_edges),
        "extra_edge_samples": [list(e) for e in extra_edges[:10]],
    }

pattern_cmp = compare_graph(parse_vf(vf_pattern), parse_lad(lad_pattern), "pattern")
target_cmp = compare_graph(parse_vf(vf_target), parse_lad(lad_target), "target")
equivalent = bool(pattern_cmp["equivalent"] and target_cmp["equivalent"])
if equivalent:
    summary = "vf and lad encodings are mathematically identical for pattern and target."
else:
    issues = []
    for cmp_item in (pattern_cmp, target_cmp):
        if cmp_item["equivalent"]:
            continue
        issues.append(
            f"{cmp_item['graph']}: nodes(vf={cmp_item['node_count_vf']},lad={cmp_item['node_count_lad']}), "
            f"missing_edges={cmp_item['missing_edges_count']}, extra_edges={cmp_item['extra_edges_count']}"
        )
    summary = "; ".join(issues) if issues else "graphs differ but no detailed issue was isolated."
print(json.dumps({
    "equivalent": equivalent,
    "summary": summary,
    "pattern": pattern_cmp,
    "target": target_cmp,
    "files": {
        "lad_pattern": str(lad_pattern),
        "lad_target": str(lad_target),
        "vf_pattern": str(vf_pattern),
        "vf_target": str(vf_target),
    }
}, separators=(",", ":")))
PY
}

append_equivalence_record() {
  local variant="$1"
  local iter_tag="$2"
  local attempt="$3"
  local seed="$4"
  local selected_for_solver="$5"
  local generation_ok="$6"
  local eq_json="$7"
  local note="$8"
  python - "$EQUIVALENCE_REPORT_FILE" "$ALGORITHM" "$variant" "$iter_tag" "$attempt" "$seed" "$selected_for_solver" "$generation_ok" "$note" "$eq_json" <<'PY'
import json
import sys
from datetime import datetime, timezone

report_path = sys.argv[1]
algo = sys.argv[2]
variant = sys.argv[3]
iter_tag = sys.argv[4]
attempt = int(sys.argv[5]) if str(sys.argv[5]).strip().isdigit() else 0
seed_raw = sys.argv[6]
selected = str(sys.argv[7]).strip().lower() == "true"
generation_ok = str(sys.argv[8]).strip().lower() == "true"
note = sys.argv[9]
raw = sys.argv[10].strip() if len(sys.argv) > 10 else ""
details = {}
if raw:
    try:
        details = json.loads(raw)
    except json.JSONDecodeError:
        details = {"equivalent": False, "summary": "equivalence_details_parse_failed", "raw": raw[:1000]}

seed = None
if seed_raw and seed_raw != "null":
    try:
        seed = int(seed_raw)
    except ValueError:
        seed = seed_raw

record = {
    "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "algorithm": algo,
    "variant": variant,
    "iteration_tag": iter_tag,
    "attempt": attempt,
    "seed": seed,
    "selected_for_solver": selected,
    "generation_ok": generation_ok,
    "equivalent": bool(details.get("equivalent")) if generation_ok else False,
    "note": note,
    "details": details,
}
with open(report_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record, separators=(",", ":")) + "\n")
PY
}

canonicalize_subgraph_pair_csv() {
  local pattern_path="$1"
  local target_path="$2"
  local out_dir="$3"
  local source_hint="${4:-auto}"
  python - "$pattern_path" "$target_path" "$out_dir" "$source_hint" <<'PY'
import re
import sys
from pathlib import Path

pattern_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])
out_dir = Path(sys.argv[3])
source_hint = str(sys.argv[4] or "auto").strip().lower()

def next_nonempty(lines, idx):
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line or line.startswith("#"):
            continue
        return line, idx
    return None, idx

def parse_lad(path: Path, prefer_vertex_labelled=True):
    lines = path.read_text(encoding="utf-8", errors="ignore").replace("\r", "").splitlines()
    idx = 0
    first, idx = next_nonempty(lines, idx)
    if first is None:
        return [], []
    n = int(first)
    adj = [set() for _ in range(max(0, n))]
    labels = [0 for _ in range(max(0, n))]
    for i in range(n):
        line, idx = next_nonempty(lines, idx)
        if line is None:
            break
        vals = []
        for tok in line.split():
            try:
                vals.append(int(tok))
            except ValueError:
                pass
        if not vals:
            continue

        use_vertex = False
        if len(vals) >= 2:
            if vals[1] == len(vals) - 2:
                use_vertex = True
            elif prefer_vertex_labelled and vals[1] >= 0 and vals[1] <= len(vals) - 2:
                use_vertex = True

        if use_vertex:
            labels[i] = vals[0]
            degree = vals[1]
            start = 2
        else:
            degree = vals[0]
            start = 1
        if degree < 0:
            degree = 0
        for j in range(degree):
            pos = start + j
            if pos >= len(vals):
                break
            v = vals[pos]
            if 0 <= v < n and v != i:
                adj[i].add(v)
                adj[v].add(i)
    return [sorted(list(s)) for s in adj], labels

def parse_vf(path: Path):
    lines = path.read_text(encoding="utf-8", errors="ignore").replace("\r", "").splitlines()
    idx = 0
    def next_nums():
        nonlocal idx
        while idx < len(lines):
            line = lines[idx]
            idx += 1
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            nums = [int(x) for x in re.findall(r"-?\d+", line)]
            if nums:
                return nums
        return None

    header = next_nums()
    if not header:
        return [], []
    n = max(0, int(header[0]))
    labels = [0 for _ in range(n)]
    for i in range(n):
        row = next_nums()
        if row is None:
            break
        if len(row) >= 2:
            labels[i] = int(row[1])
    adj = [set() for _ in range(n)]
    for i in range(n):
        count_line = next_nums()
        if not count_line:
            break
        m = max(0, int(count_line[0]))
        for _ in range(m):
            edge = next_nums()
            if not edge:
                break
            j = None
            if len(edge) >= 2:
                a, b = int(edge[0]), int(edge[1])
                if a == i and 0 <= b < n:
                    j = b
                elif b == i and 0 <= a < n:
                    j = a
                elif 0 <= a < n:
                    j = a
                elif 0 <= b < n:
                    j = b
            else:
                a = int(edge[0])
                if 0 <= a < n:
                    j = a
            if j is None or j == i:
                continue
            adj[i].add(j)
            adj[j].add(i)
    return [sorted(list(s)) for s in adj], labels

def sanitize_undirected_simple_adj(adj):
    n = len(adj)
    clean = [set() for _ in range(n)]
    for u, nbrs in enumerate(adj):
        for raw_v in nbrs:
            try:
                v = int(raw_v)
            except (TypeError, ValueError):
                continue
            if v < 0 or v >= n or v == u:
                continue
            clean[u].add(v)
            clean[v].add(u)
    return [sorted(list(s)) for s in clean]

def normalize_labels(labels, n):
    out = []
    for i in range(n):
        try:
            out.append(int(labels[i]))
        except Exception:
            out.append(i % 4)
    return out

def write_vf(path: Path, adj, labels):
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for i, label in enumerate(labels):
            fh.write(f"{i} {label}\n")
        for i, neighbors in enumerate(adj):
            fh.write(f"{len(neighbors)}\n")
            for v in neighbors:
                fh.write(f"{i} {v}\n")

def write_vertex_labelled_lad(path: Path, adj, labels):
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for i, neighbors in enumerate(adj):
            line = f"{labels[i]} {len(neighbors)}"
            if neighbors:
                line += " " + " ".join(str(v) for v in neighbors)
            fh.write(line + "\n")

def detect_format(path: Path):
    ext = path.suffix.lower()
    if ext == ".vf" or ext == ".grf":
        return "vf"
    if ext == ".lad":
        return "lad"
    return ""

if source_hint not in {"vf", "lad", "auto"}:
    source_hint = "auto"

fmt_pattern = detect_format(pattern_path)
fmt_target = detect_format(target_path)
if source_hint == "auto":
    if fmt_pattern == "vf" and fmt_target == "vf":
        source_hint = "vf"
    elif fmt_pattern == "lad" and fmt_target == "lad":
        source_hint = "lad"
    elif fmt_pattern and fmt_target and fmt_pattern != fmt_target:
        raise SystemExit("Mixed or unsupported formats for subgraph input.")
    else:
        source_hint = "vf" if fmt_pattern == "vf" or fmt_target == "vf" else "lad"

if source_hint == "vf":
    pattern_adj, pattern_labels = parse_vf(pattern_path)
    target_adj, target_labels = parse_vf(target_path)
else:
    pattern_adj, pattern_labels = parse_lad(pattern_path, prefer_vertex_labelled=True)
    target_adj, target_labels = parse_lad(target_path, prefer_vertex_labelled=True)

pattern_adj = sanitize_undirected_simple_adj(pattern_adj)
target_adj = sanitize_undirected_simple_adj(target_adj)
pattern_labels = normalize_labels(pattern_labels, len(pattern_adj))
target_labels = normalize_labels(target_labels, len(target_adj))

out_dir.mkdir(parents=True, exist_ok=True)
vf_pattern = out_dir / "canonical_pattern.vf"
vf_target = out_dir / "canonical_target.vf"
lad_pattern = out_dir / "canonical_pattern.lad"
lad_target = out_dir / "canonical_target.lad"

write_vf(vf_pattern, pattern_adj, pattern_labels)
write_vf(vf_target, target_adj, target_labels)
write_vertex_labelled_lad(lad_pattern, pattern_adj, pattern_labels)
write_vertex_labelled_lad(lad_target, target_adj, target_labels)

print(",".join([str(lad_pattern), str(lad_target), str(vf_pattern), str(vf_target)]))
PY
}

if [ "$INPUT_MODE" = "generate" ]; then
  seed_trimmed="$(echo "${GENERATOR_SEED_RAW}" | tr -d '\r' | xargs)"
  if [[ "${seed_trimmed}" =~ ^-?[0-9]+$ ]]; then
    SEED_USED="${seed_trimmed}"
  else
    SEED_USED="$(python -c "import secrets; print(secrets.randbits(31))")"
  fi
fi

generate_graphs_for_run() {
  local variant="$1"
  local iter="$2"
  local gen_dir="outputs/generated/${ALGORITHM}/${variant}/iter_${iter}"
  mkdir -p "$gen_dir"
  local max_attempts=1
  if [ "$ALGORITHM" = "subgraph" ]; then
    max_attempts=10
  fi

  local selected_seed=""
  local selected_files=""
  local selected_output=""
  local selected_status=1
  local selected_equivalent=1
  local had_successful_generation=0

  local attempt
  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    GEN_COUNTER=$((GEN_COUNTER + 1))
    local seed
    seed="$(python -c "import sys; base=int(sys.argv[1]); offset=int(sys.argv[2]); print(base + offset)" "$SEED_USED" "$GEN_COUNTER")"
    local output status files
    local -a gen_args
    gen_args=(--algorithm "$ALGORITHM" --n "$GENERATOR_N" --density "$GENERATOR_DENSITY" --seed "$seed" --out-dir "$gen_dir")
    if [ "$ALGORITHM" != "dijkstra" ]; then
      gen_args+=(--k "$GENERATOR_K")
    fi
    output="$(python utilities/generate_graphs.py "${gen_args[@]}" 2>&1)"
    status=$?
    files="$(echo "$output" | tail -n 1 | tr -d '\r')"

    if [ "$ALGORITHM" != "subgraph" ]; then
      if [ $status -ne 0 ] || [ -z "$files" ]; then
        echo "Graph generation failed." >> outputs/result.txt
        if [ -n "$output" ]; then
          echo "$output" >> outputs/result.txt
        fi
        return 1
      fi
      selected_seed="$seed"
      selected_files="$files"
      selected_output="$output"
      selected_status=0
      break
    fi

    if [ $status -ne 0 ] || [ -z "$files" ]; then
      local gen_fail_json
      gen_fail_json='{"equivalent":false,"summary":"graph_generation_failed"}'
      local selected_for_solver="false"
      if [ "$attempt" -eq "$max_attempts" ] && [ "$had_successful_generation" -eq 0 ]; then
        selected_for_solver="true"
      fi
      append_equivalence_record "$variant" "$iter" "$attempt" "$seed" "$selected_for_solver" "false" "$gen_fail_json" "generation_failed"
      if [ "$attempt" -eq "$max_attempts" ] && [ "$had_successful_generation" -eq 0 ]; then
        echo "Graph generation failed after ${max_attempts} attempts for ${variant} iteration ${iter}." >> outputs/result.txt
        if [ -n "$output" ]; then
          echo "$output" >> outputs/result.txt
        fi
        return 1
      fi
      continue
    fi

    had_successful_generation=1
    local -a attempt_files
    IFS=',' read -ra attempt_files <<< "$files"
    local lad_pattern=""
    local lad_target=""
    local vf_pattern=""
    local vf_target=""
    for f in "${attempt_files[@]}"; do
      case "$f" in
        *pattern*.lad) lad_pattern="$f" ;;
        *target*.lad) lad_target="$f" ;;
        *pattern*.vf) vf_pattern="$f" ;;
        *target*.vf) vf_target="$f" ;;
      esac
    done
    if [ -z "$lad_pattern" ] || [ -z "$lad_target" ] || [ -z "$vf_pattern" ] || [ -z "$vf_target" ]; then
      for f in "${attempt_files[@]}"; do
        case "$f" in
          *.lad)
            if [ -z "$lad_pattern" ]; then lad_pattern="$f"; else lad_target="$f"; fi
            ;;
          *.vf)
            if [ -z "$vf_pattern" ]; then vf_pattern="$f"; else vf_target="$f"; fi
            ;;
        esac
      done
    fi

    local eq_json equivalent summary
    if [ -n "$lad_pattern" ] && [ -n "$lad_target" ] && [ -n "$vf_pattern" ] && [ -n "$vf_target" ]; then
      eq_json="$(check_subgraph_equivalence_json "$lad_pattern" "$lad_target" "$vf_pattern" "$vf_target")"
      equivalent="$(python - "$eq_json" <<'PY'
import json,sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    payload = {}
print("1" if payload.get("equivalent") else "0")
PY
)"
      summary="$(python - "$eq_json" <<'PY'
import json,sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    payload = {}
print(str(payload.get("summary", "")))
PY
)"
    else
      eq_json='{"equivalent":false,"summary":"missing_expected_vf_or_lad_files"}'
      equivalent="0"
      summary="missing_expected_vf_or_lad_files"
    fi

    local selected_for_solver="false"
    if [ "$equivalent" = "1" ]; then
      selected_for_solver="true"
      selected_seed="$seed"
      selected_files="$files"
      selected_output="$output"
      selected_status=0
      selected_equivalent=1
      append_equivalence_record "$variant" "$iter" "$attempt" "$seed" "$selected_for_solver" "true" "$eq_json" "$summary"
      break
    fi

    if [ "$attempt" -eq "$max_attempts" ]; then
      selected_for_solver="true"
      selected_seed="$seed"
      selected_files="$files"
      selected_output="$output"
      selected_status=0
      selected_equivalent=0
    fi
    append_equivalence_record "$variant" "$iter" "$attempt" "$seed" "$selected_for_solver" "true" "$eq_json" "$summary"
  done

  if [ $selected_status -ne 0 ] || [ -z "$selected_files" ]; then
    echo "Graph generation failed." >> outputs/result.txt
    if [ -n "$selected_output" ]; then
      echo "$selected_output" >> outputs/result.txt
    fi
    return 1
  fi
  if [ "$selected_equivalent" -ne 1 ] && [ "$ALGORITHM" = "subgraph" ]; then
    echo "[Equivalence] Subgraph generator outputs were not mathematically identical after ${max_attempts} attempts; using attempt ${max_attempts} anyway." >> outputs/result.txt
  fi

  if [ -z "${VIS_SEED:-}" ]; then
    if [[ "$variant" == "dijkstra_baseline" && "$iter" == "1" ]]; then
      VIS_SEED="$selected_seed"
    elif [[ "$variant" == "glasgow_iter" && "$iter" == "1" ]]; then
      VIS_SEED="$selected_seed"
    elif [[ "$variant" == "vf3_iter"* && "$iter" == 1* ]]; then
      VIS_SEED="$selected_seed"
    elif [[ "$variant" == "subgraph_iter" && "$iter" == "1" ]]; then
      VIS_SEED="$selected_seed"
    fi
  fi

  IFS=',' read -ra FILES <<< "$selected_files"
  if [ "$ALGORITHM" = "subgraph" ]; then
    local src_vf_pattern=""
    local src_vf_target=""
    local src_lad_pattern=""
    local src_lad_target=""
    local f
    for f in "${FILES[@]}"; do
      case "$f" in
        *pattern*.vf) src_vf_pattern="$f" ;;
        *target*.vf) src_vf_target="$f" ;;
        *pattern*.lad) src_lad_pattern="$f" ;;
        *target*.lad) src_lad_target="$f" ;;
      esac
    done
    if [ -z "$src_vf_pattern" ] || [ -z "$src_vf_target" ]; then
      for f in "${FILES[@]}"; do
        case "$f" in
          *.vf)
            if [ -z "$src_vf_pattern" ]; then src_vf_pattern="$f"; else src_vf_target="$f"; fi
            ;;
          *.lad)
            if [ -z "$src_lad_pattern" ]; then src_lad_pattern="$f"; else src_lad_target="$f"; fi
            ;;
        esac
      done
    fi

    local canonical_hint="vf"
    local canonical_p=""
    local canonical_t=""
    if [ -n "$src_vf_pattern" ] && [ -n "$src_vf_target" ]; then
      canonical_p="$src_vf_pattern"
      canonical_t="$src_vf_target"
      canonical_hint="vf"
    elif [ -n "$src_lad_pattern" ] && [ -n "$src_lad_target" ]; then
      canonical_p="$src_lad_pattern"
      canonical_t="$src_lad_target"
      canonical_hint="lad"
    else
      echo "Subgraph canonicalization failed: missing source pattern/target pair." >> outputs/result.txt
      return 1
    fi

    local canonical_csv canonical_status canonical_dir
    canonical_dir="${gen_dir}/canonical"
    canonical_csv="$(canonicalize_subgraph_pair_csv "$canonical_p" "$canonical_t" "$canonical_dir" "$canonical_hint" 2>&1)"
    canonical_status=$?
    if [ $canonical_status -ne 0 ] || [ -z "$canonical_csv" ]; then
      echo "Subgraph canonicalization failed." >> outputs/result.txt
      if [ -n "$canonical_csv" ]; then
        echo "$canonical_csv" >> outputs/result.txt
      fi
      return 1
    fi
    selected_files="$canonical_csv"
    IFS=',' read -ra FILES <<< "$selected_files"

    local metadata_path
    metadata_path="${gen_dir}/metadata.json"
    python - "$metadata_path" "$selected_files" "$selected_seed" <<'PY'
import json
import sys
from pathlib import Path

meta_path = Path(sys.argv[1])
files_csv = sys.argv[2]
seed_raw = sys.argv[3]
files = [p.strip() for p in str(files_csv).split(",") if p.strip()]

meta = {}
if meta_path.exists():
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
if not isinstance(meta, dict):
    meta = {}
meta["files"] = files
meta["canonicalized"] = True
meta["canonical_source"] = "vf_preferred"
try:
    meta["seed"] = int(seed_raw)
except Exception:
    meta["seed"] = seed_raw
meta_path.parent.mkdir(parents=True, exist_ok=True)
meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
PY

    SUBGRAPH_VF_FILES=()
    SUBGRAPH_LAD_FILES=()
    for f in "${FILES[@]}"; do
      case "$f" in
        *.vf) SUBGRAPH_VF_FILES+=("$f") ;;
        *.lad) SUBGRAPH_LAD_FILES+=("$f") ;;
      esac
    done
  fi
  return 0
}

finish_run() {
  local end_ns duration_ms
  end_ns="$(date +%s%N)"
  if [ -n "${SOLVER_TIME_MS_TOTAL:-}" ]; then
    duration_ms="$SOLVER_TIME_MS_TOTAL"
  else
    duration_ms="$(python -c "import sys; start=int(sys.argv[1]); end=int(sys.argv[2]); print(f'{(end-start)/1_000_000:.3f}')" "$RUN_STARTED_NS" "$end_ns")"
  fi
  echo "RUN_DURATION_MS=$duration_ms" >> "$GITHUB_OUTPUT"
}

if [ "${BINARIES_READY:-}" != "1" ]; then
  echo "Failed to download prebuilt binaries." >> outputs/result.txt
  if [ -s outputs/binaries_download_error.txt ]; then
    cat outputs/binaries_download_error.txt >> outputs/result.txt
  fi
  finish_run
  echo "EXIT_CODE=1" >> "$GITHUB_OUTPUT"
  echo "REQUEST_ID=${REQUEST_ID}" >> "$GITHUB_OUTPUT"
  exit 0
fi

if [ "$INPUT_MODE" != "generate" ]; then
  # Parse input files
  IFS=',' read -ra FILES <<< "$INPUT_FILES"

  if [ "$ALGORITHM" = "dijkstra" ] && [ ${#FILES[@]} -lt 1 ]; then
    echo "No input file provided for Dijkstra." >> outputs/result.txt
    finish_run
    echo "EXIT_CODE=1" >> "$GITHUB_OUTPUT"
    echo "REQUEST_ID=${REQUEST_ID}" >> "$GITHUB_OUTPUT"
    exit 0
  fi
  if [ "$ALGORITHM" != "dijkstra" ] && [ ${#FILES[@]} -lt 2 ]; then
    echo "Pattern/target files are required for $ALGORITHM." >> outputs/result.txt
    finish_run
    echo "EXIT_CODE=1" >> "$GITHUB_OUTPUT"
    echo "REQUEST_ID=${REQUEST_ID}" >> "$GITHUB_OUTPUT"
    exit 0
  fi

  # Normalize graph inputs so the smaller graph is always the pattern/subgraph.
  # (Order of clicks in the UI should not matter.)
  if [ "$ALGORITHM" = "glasgow" ] || [ "$ALGORITHM" = "vf3" ] || [ "$ALGORITHM" = "subgraph" ]; then
    graph_nodes() {
      python -c "import re,sys,pathlib; path=pathlib.Path(sys.argv[1]); lines=path.read_text(encoding='utf-8',errors='ignore').splitlines() if path.exists() else []; num=next((m.group(1) for line in lines if (s:=line.strip()) and not s.startswith('#') and (m:=re.match(r'^(-?\\\\d+)', s))), ''); print(num)" "$1" 2>/dev/null || true
    }

    file0="${FILES[0]}"
    file1="${FILES[1]}"
    nodes0="$(graph_nodes "$file0")"
    nodes1="$(graph_nodes "$file1")"
    size0="$(stat -c%s "$file0" 2>/dev/null || echo 0)"
    size1="$(stat -c%s "$file1" 2>/dev/null || echo 0)"

    swap=0
    if [[ "$nodes0" =~ ^[0-9]+$ ]] && [[ "$nodes1" =~ ^[0-9]+$ ]]; then
      if [ "$nodes0" -gt "$nodes1" ]; then
        swap=1
      elif [ "$nodes0" -eq "$nodes1" ] && [ "$size0" -gt "$size1" ]; then
        swap=1
      fi
    else
      if [ "$size0" -gt "$size1" ]; then
        swap=1
      fi
    fi

    if [ "$swap" -eq 1 ]; then
      FILES[0]="$file1"
      FILES[1]="$file0"
      echo "Normalized inputs (smaller graph used as pattern/subgraph)." >> outputs/result.txt
    fi
  fi

  if [ "$ALGORITHM" = "subgraph" ]; then
    mkdir -p outputs/converted
    conv_out="$(canonicalize_subgraph_pair_csv "${FILES[0]}" "${FILES[1]}" "outputs/converted" "auto" 2>&1)"
    status=$?
    if [ $status -ne 0 ]; then
      echo "Failed to convert premade subgraph inputs." >> outputs/result.txt
      echo "$conv_out" >> outputs/result.txt
      finish_run
      echo "EXIT_CODE=1" >> "$GITHUB_OUTPUT"
      echo "REQUEST_ID=${REQUEST_ID}" >> "$GITHUB_OUTPUT"
      exit 0
    fi
    IFS=',' read -ra FILES <<< "$conv_out"
    SUBGRAPH_VF_FILES=()
    SUBGRAPH_LAD_FILES=()
    for f in "${FILES[@]}"; do
      case "$f" in
        *.vf) SUBGRAPH_VF_FILES+=("$f") ;;
        *.lad) SUBGRAPH_LAD_FILES+=("$f") ;;
      esac
    done
    if [ ${#SUBGRAPH_LAD_FILES[@]} -ge 2 ] && [ ${#SUBGRAPH_VF_FILES[@]} -ge 2 ]; then
      local_eq_json="$(check_subgraph_equivalence_json "${SUBGRAPH_LAD_FILES[0]}" "${SUBGRAPH_LAD_FILES[1]}" "${SUBGRAPH_VF_FILES[0]}" "${SUBGRAPH_VF_FILES[1]}")"
      local_eq_ok="$(python - "$local_eq_json" <<'PY'
import json,sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    payload = {}
print("1" if payload.get("equivalent") else "0")
PY
)"
      local_note="$(python - "$local_eq_json" <<'PY'
import json,sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    payload = {}
print(str(payload.get("summary", "")))
PY
)"
      append_equivalence_record "premade_conversion" "1" "1" "null" "true" "true" "$local_eq_json" "$local_note"
      if [ "$local_eq_ok" != "1" ]; then
        echo "[Equivalence] Premade subgraph translation (.vf/.lad) is not mathematically identical." >> outputs/result.txt
      fi
    else
      append_equivalence_record "premade_conversion" "1" "1" "null" "true" "true" '{"equivalent":false,"summary":"missing_converted_vf_or_lad_files"}' "missing_converted_vf_or_lad_files"
      echo "[Equivalence] Premade subgraph translation did not produce both .vf and .lad pairs." >> outputs/result.txt
    fi
  fi
fi

ITERATIONS="1"
if [[ "$ITERATIONS_RAW" =~ ^[0-9]+$ ]] && [ "$ITERATIONS_RAW" -ge 1 ]; then
  ITERATIONS="$ITERATIONS_RAW"
fi

WARMUP="0"
if [[ "${WARMUP_RAW}" =~ ^[0-9]+$ ]]; then
  WARMUP="${WARMUP_RAW}"
fi
if [ "$WARMUP" -gt 50 ]; then
  WARMUP="50"
fi
WARMUP_REQUESTED="$WARMUP"
