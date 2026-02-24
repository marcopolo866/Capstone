set -uo pipefail
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
  if [ $status -ne 0 ] || [ -z "$files" ]; then
    echo "Graph generation failed." >> outputs/result.txt
    if [ -n "$output" ]; then
      echo "$output" >> outputs/result.txt
    fi
    return 1
  fi
  if [ -z "${VIS_SEED:-}" ]; then
    if [[ "$variant" == "dijkstra_baseline" && "$iter" == "1" ]]; then
      VIS_SEED="$seed"
    elif [[ "$variant" == "glasgow_iter" && "$iter" == "1" ]]; then
      VIS_SEED="$seed"
    elif [[ "$variant" == "vf3_iter"* && "$iter" == 1* ]]; then
      VIS_SEED="$seed"
    fi
  fi
  IFS=',' read -ra FILES <<< "$files"
  if [ "$ALGORITHM" = "subgraph" ]; then
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
    conv_out="$(printf '%s\n' \
      'import re' \
      'import sys' \
      'from pathlib import Path' \
      '' \
      'pattern_path = Path(sys.argv[1])' \
      'target_path = Path(sys.argv[2])' \
      'out_dir = Path(\"outputs/converted\")' \
      'out_dir.mkdir(parents=True, exist_ok=True)' \
      '' \
      'def read_lad(path: Path):' \
      '    with path.open(\"r\", encoding=\"utf-8\") as fh:' \
      '        first = fh.readline()' \
      '        if not first:' \
      '            raise ValueError(\"Empty LAD file\")' \
      '        n = int(first.strip())' \
      '        adj = [set() for _ in range(n)]' \
      '        labels = [0 for _ in range(n)]' \
      '        labelled = False' \
      '        for i in range(n):' \
      '            line = fh.readline()' \
      '            if not line:' \
      '                break' \
      '            parts = line.strip().split()' \
      '            if not parts:' \
      '                continue' \
      '            nums = [int(x) for x in parts]' \
      '            if len(nums) >= 2 and nums[1] == len(nums) - 2:' \
      '                labelled = True' \
      '                labels[i] = nums[0]' \
      '                d = nums[1]' \
      '                start = 2' \
      '            else:' \
      '                d = nums[0]' \
      '                start = 1' \
      '            for v in nums[start:start + d]:' \
      '                if 0 <= v < n and v != i:' \
      '                    adj[i].add(v)' \
      '    for i in range(n):' \
      '        for j in list(adj[i]):' \
      '            adj[j].add(i)' \
      '    return [sorted(list(s)) for s in adj], (labels if labelled else None)' \
      '' \
      'def read_vf(path: Path):' \
      '    def next_int_line(handle):' \
      '        while True:' \
      '            line = handle.readline()' \
      '            if not line:' \
      '                return None' \
      '            stripped = line.strip()' \
      '            if not stripped or stripped.startswith(\"#\"):' \
      '                continue' \
      '            nums = [int(x) for x in re.findall(r\"-?\\d+\", line)]' \
      '            if nums:' \
      '                return nums' \
      '    with path.open(\"r\", encoding=\"utf-8\") as fh:' \
      '        header = next_int_line(fh)' \
      '        if not header:' \
      '            raise ValueError(\"Empty VF file\")' \
      '        n = int(header[0])' \
      '        labels = [0 for _ in range(n)]' \
      '        for i in range(n):' \
      '            row = next_int_line(fh)' \
      '            if row is None:' \
      '                break' \
      '            if len(row) >= 2:' \
      '                labels[i] = row[1]' \
      '        adj = [set() for _ in range(n)]' \
      '        for i in range(n):' \
      '            count_line = next_int_line(fh)' \
      '            if not count_line:' \
      '                break' \
      '            m = int(count_line[0])' \
      '            for _ in range(m):' \
      '                edge_nums = next_int_line(fh)' \
      '                if not edge_nums:' \
      '                    break' \
      '                if len(edge_nums) >= 2:' \
      '                    a, b = edge_nums[0], edge_nums[1]' \
      '                    if a == i and 0 <= b < n:' \
      '                        j = b' \
      '                    elif b == i and 0 <= a < n:' \
      '                        j = a' \
      '                    else:' \
      '                        j = a if 0 <= a < n else (b if 0 <= b < n else None)' \
      '                else:' \
      '                    j = edge_nums[0] if 0 <= edge_nums[0] < n else None' \
      '                if j is None or j == i:' \
      '                    continue' \
      '                adj[i].add(j)' \
      '    for i in range(n):' \
      '        for j in list(adj[i]):' \
      '            adj[j].add(i)' \
      '    return [sorted(list(s)) for s in adj], labels' \
      '' \
      'def write_lad(path: Path, adj, labels):' \
      '    with path.open(\"w\", encoding=\"utf-8\") as fh:' \
      '        fh.write(f\"{len(adj)}\\n\")' \
      '        for i, neighbors in enumerate(adj):' \
      '            line = f\"{labels[i]} {len(neighbors)}\"' \
      '            if neighbors:' \
      '                line += \" \" + \" \".join(str(v) for v in neighbors)' \
      '            fh.write(line + \"\\n\")' \
      '' \
      'def write_vf(path: Path, adj, labels):' \
      '    with path.open(\"w\", encoding=\"utf-8\") as fh:' \
      '        fh.write(f\"{len(adj)}\\n\")' \
      '        for i, label in enumerate(labels):' \
      '            fh.write(f\"{i} {label}\\n\")' \
      '        for i, neighbors in enumerate(adj):' \
      '            fh.write(f\"{len(neighbors)}\\n\")' \
      '            for v in neighbors:' \
      '                fh.write(f\"{i} {v}\\n\")' \
      '' \
      'def detect_format(path: Path):' \
      '    if path.suffix.lower() == \".lad\":' \
      '        return \"lad\"' \
      '    if path.suffix.lower() == \".vf\":' \
      '        return \"vf\"' \
      '    return \"\"' \
      '' \
      'fmt_pattern = detect_format(pattern_path)' \
      'fmt_target = detect_format(target_path)' \
      'if fmt_pattern != fmt_target or fmt_pattern == \"\":' \
      '    raise SystemExit(\"Mixed or unsupported formats for subgraph premade input.\")' \
      '' \
      'def ensure_labels(labels, n):' \
      '    if labels is None or len(labels) != n:' \
      '        return [i % 4 for i in range(n)]' \
      '    return labels' \
      '' \
      'if fmt_pattern == \"lad\":' \
      '    pattern_adj, pattern_labels = read_lad(pattern_path)' \
      '    target_adj, target_labels = read_lad(target_path)' \
      'else:' \
      '    pattern_adj, pattern_labels = read_vf(pattern_path)' \
      '    target_adj, target_labels = read_vf(target_path)' \
      '' \
      'pattern_labels = ensure_labels(pattern_labels, len(pattern_adj))' \
      'target_labels = ensure_labels(target_labels, len(target_adj))' \
      '' \
      'lad_pattern = out_dir / \"pattern.lad\"' \
      'lad_target = out_dir / \"target.lad\"' \
      'vf_pattern = out_dir / \"pattern.vf\"' \
      'vf_target = out_dir / \"target.vf\"' \
      '' \
      'write_lad(lad_pattern, pattern_adj, pattern_labels)' \
      'write_lad(lad_target, target_adj, target_labels)' \
      'write_vf(vf_pattern, pattern_adj, pattern_labels)' \
      'write_vf(vf_target, target_adj, target_labels)' \
      '' \
      'print(\",\".join([str(lad_pattern), str(lad_target), str(vf_pattern), str(vf_target)]))' \
      | python - "${FILES[0]}" "${FILES[1]}")"
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

