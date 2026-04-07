import datetime
import json
import os
from pathlib import Path

def load_merged_env():
    merged = {str(k): str(v) for k, v in os.environ.items()}
    candidates = [
        merged.get("RUN_METRICS_JSON", ""),
        merged.get("METRICS_JSON_PATH", ""),
        "outputs/run_metrics.json",
    ]
    for raw_path in candidates:
        path = Path(str(raw_path or "").strip())
        if not path:
            continue
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            merged[str(key)] = "" if value is None else str(value)
        merged["RUN_METRICS_JSON"] = str(path)
        break
    return merged


env = load_merged_env()


def parse_json_env(name: str):
    raw = env.get(name, "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def merge_statistical_tests(previous, current):
    prev = previous if isinstance(previous, dict) else {}
    cur = current if isinstance(current, dict) else {}
    merged = {}

    merged["metric"] = cur.get("metric") or prev.get("metric") or "runtime_ms"
    alpha = cur.get("alpha", prev.get("alpha"))
    if alpha is not None:
        merged["alpha"] = alpha

    notes = []
    for source in (prev.get("notes"), cur.get("notes")):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text and text not in notes:
                notes.append(text)
    if notes:
        merged["notes"] = notes

    pairs = []
    seen = set()
    for source in (prev.get("pairs"), cur.get("pairs")):
        if not isinstance(source, list):
            continue
        for row in source:
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("variant_id") or ""),
                str(row.get("baseline_variant_id") or ""),
                str(row.get("mode") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            pairs.append(row)
    merged["pairs"] = pairs
    return merged

algorithm = env.get("ALGORITHM_INPUT", "")
exit_code = env.get("EXIT_CODE", "")
request_id = env.get("REQUEST_ID_INPUT", "")
timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
input_mode = env.get("INPUT_MODE_INPUT", "")
input_files = env.get("INPUT_FILES_INPUT", "")
gen_n = env.get("GENERATOR_N_INPUT", "")
gen_k = env.get("GENERATOR_K_INPUT", "")
gen_density = env.get("GENERATOR_DENSITY_INPUT", "")
seed_used = env.get("SEED_USED", "")
via_node = env.get("VIA_NODE_INPUT", "")

result_txt = Path("outputs/result.txt")
text = ""
if result_txt.exists():
    text = result_txt.read_text(encoding="utf-8", errors="replace")

if exit_code == "0":
    status = "success"
    output = text or "No output"
    error = ""
else:
    status = "error"
    output = ""
    error = text or "Unknown error"

Path("outputs").mkdir(parents=True, exist_ok=True)
data = {
    "algorithm": algorithm,
    "timestamp": timestamp,
    "status": status,
    "output": output,
    "error": error,
    "request_id": request_id,
}
vis_path = Path("outputs/visualization.json")
if vis_path.exists():
    try:
        data["visualization"] = json.loads(vis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data["visualization_error"] = "Failed to parse visualization.json"
        try:
            raw = vis_path.read_text(encoding="utf-8", errors="replace")
            data["visualization_raw"] = raw[:2000]
            if len(raw) > 2000:
                data["visualization_raw_truncated"] = True
        except OSError:
            pass
else:
    if input_mode == "generate":
        data["visualization_error"] = "Visualization data missing"

equivalence_path = Path("outputs/equivalence_report.jsonl")
equivalence_records = []
if equivalence_path.exists():
    for raw in equivalence_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            equivalence_records.append(json.loads(line))
        except json.JSONDecodeError:
            equivalence_records.append(
                {
                    "algorithm": algorithm,
                    "selected_for_solver": False,
                    "equivalent": False,
                    "note": "equivalence_record_parse_failed",
                    "raw": line[:2000],
                }
            )
if equivalence_records:
    selected = [r for r in equivalence_records if bool(r.get("selected_for_solver"))]
    selected_failures = [r for r in selected if not bool(r.get("equivalent"))]
    data["equivalence_check"] = {
        "applies": True,
        "records": equivalence_records,
        "selected_for_solver_count": len(selected),
        "selected_for_solver_failures": len(selected_failures),
        "graphs_not_mathematically_identical": len(selected_failures) > 0,
    }
inputs = {"input_mode": input_mode, "input_files": input_files}
if gen_n:
    try:
        inputs["n"] = int(gen_n)
    except ValueError:
        inputs["n"] = gen_n
if gen_k:
    try:
        inputs["k"] = int(gen_k)
    except ValueError:
        inputs["k"] = gen_k
if gen_density:
    try:
        inputs["density"] = float(gen_density)
    except ValueError:
        inputs["density"] = gen_density
if seed_used:
    try:
        inputs["seed"] = int(seed_used)
    except ValueError:
        inputs["seed"] = seed_used
if via_node:
    inputs["via"] = via_node
if inputs:
    data["inputs"] = inputs
variant_metadata = parse_json_env("VARIANT_METADATA_JSON")
if isinstance(variant_metadata, list):
    data["variant_metadata"] = variant_metadata
iterations = env.get("ITERATIONS", "").strip()
if iterations:
    try:
        data["iterations"] = int(iterations)
    except ValueError:
        pass
warmup = env.get("WARMUP", "").strip()
if warmup:
    try:
        data["warmup"] = int(warmup)
    except ValueError:
        pass
duration_ms = env.get("RUN_DURATION_MS", "").strip()
if duration_ms:
    try:
        data["run_duration_ms"] = float(duration_ms)
    except ValueError:
        pass
timings_ms = parse_json_env("TIMINGS_MS_JSON")
if not isinstance(timings_ms, dict):
    timings_ms = {}
if not timings_ms and algorithm == "dijkstra":
    baseline = env.get("DIJKSTRA_BASELINE_MS", "")
    llm = env.get("DIJKSTRA_LLM_MS", "")
    gemini = env.get("DIJKSTRA_GEMINI_MS", "")
    if baseline:
        timings_ms["baseline"] = float(baseline)
    if llm:
        timings_ms["llm"] = float(llm)
        timings_ms["chatgpt"] = float(llm)
    if gemini:
        timings_ms["gemini"] = float(gemini)
elif not timings_ms and algorithm == "glasgow":
    first = env.get("GLASGOW_FIRST_MS", "")
    all_ms = env.get("GLASGOW_ALL_MS", "")
    if first:
        timings_ms["first"] = float(first)
    if all_ms:
        timings_ms["all"] = float(all_ms)
    gemini_first = env.get("GLASGOW_GEMINI_FIRST_MS", "")
    gemini_all = env.get("GLASGOW_GEMINI_ALL_MS", "")
    chatgpt_first = env.get("GLASGOW_CHATGPT_FIRST_MS", "")
    chatgpt_all = env.get("GLASGOW_CHATGPT_ALL_MS", "")
    if gemini_first:
        timings_ms["gemini_first"] = float(gemini_first)
    if gemini_all:
        timings_ms["gemini_all"] = float(gemini_all)
    if chatgpt_first:
        timings_ms["chatgpt_first"] = float(chatgpt_first)
    if chatgpt_all:
        timings_ms["chatgpt_all"] = float(chatgpt_all)
elif not timings_ms and algorithm == "vf3":
    def maybe_add(name: str, key: str) -> None:
        value = env.get(key, "")
        if value:
            timings_ms[name] = float(value)

    maybe_add("baseline_first", "VF3_BASE_FIRST_MS")
    maybe_add("baseline_all", "VF3_BASE_ALL_MS")
    maybe_add("gemini_first", "VF3_GEMINI_FIRST_MS")
    maybe_add("gemini_all", "VF3_GEMINI_ALL_MS")
    maybe_add("chatgpt_first", "VF3_CHATGPT_FIRST_MS")
    maybe_add("chatgpt_all", "VF3_CHATGPT_ALL_MS")
elif not timings_ms and algorithm == "subgraph":
    def maybe_add(name: str, key: str) -> None:
        value = env.get(key, "")
        if value:
            timings_ms[name] = float(value)

    maybe_add("vf3_baseline_first", "VF3_BASE_FIRST_MS")
    maybe_add("vf3_baseline_all", "VF3_BASE_ALL_MS")
    maybe_add("vf3_gemini_first", "VF3_GEMINI_FIRST_MS")
    maybe_add("vf3_gemini_all", "VF3_GEMINI_ALL_MS")
    maybe_add("vf3_chatgpt_first", "VF3_CHATGPT_FIRST_MS")
    maybe_add("vf3_chatgpt_all", "VF3_CHATGPT_ALL_MS")
    maybe_add("glasgow_baseline_first", "GLASGOW_FIRST_MS")
    maybe_add("glasgow_baseline_all", "GLASGOW_ALL_MS")
    maybe_add("glasgow_gemini_first", "GLASGOW_GEMINI_FIRST_MS")
    maybe_add("glasgow_gemini_all", "GLASGOW_GEMINI_ALL_MS")
    maybe_add("glasgow_chatgpt_first", "GLASGOW_CHATGPT_FIRST_MS")
    maybe_add("glasgow_chatgpt_all", "GLASGOW_CHATGPT_ALL_MS")
if algorithm == "subgraph":
    phase = env.get("SUBGRAPH_PHASE", "").strip().lower()
    data["subgraph_phase"] = phase or "full"
if timings_ms:
    data["timings_ms"] = timings_ms

timings_ms_stdev = parse_json_env("TIMINGS_MS_STDEV_JSON")
if not isinstance(timings_ms_stdev, dict):
    timings_ms_stdev = {}
if not timings_ms_stdev and algorithm == "dijkstra":
    baseline = env.get("DIJKSTRA_BASELINE_MS_STDEV", "")
    llm = env.get("DIJKSTRA_LLM_MS_STDEV", "")
    gemini = env.get("DIJKSTRA_GEMINI_MS_STDEV", "")
    if baseline:
        timings_ms_stdev["baseline"] = float(baseline)
    if llm:
        timings_ms_stdev["llm"] = float(llm)
        timings_ms_stdev["chatgpt"] = float(llm)
    if gemini:
        timings_ms_stdev["gemini"] = float(gemini)
elif not timings_ms_stdev and algorithm == "glasgow":
    first = env.get("GLASGOW_FIRST_MS_STDEV", "")
    all_ms = env.get("GLASGOW_ALL_MS_STDEV", "")
    if first:
        timings_ms_stdev["first"] = float(first)
    if all_ms:
        timings_ms_stdev["all"] = float(all_ms)
    gemini_first = env.get("GLASGOW_GEMINI_FIRST_MS_STDEV", "")
    gemini_all = env.get("GLASGOW_GEMINI_ALL_MS_STDEV", "")
    chatgpt_first = env.get("GLASGOW_CHATGPT_FIRST_MS_STDEV", "")
    chatgpt_all = env.get("GLASGOW_CHATGPT_ALL_MS_STDEV", "")
    if gemini_first:
        timings_ms_stdev["gemini_first"] = float(gemini_first)
    if gemini_all:
        timings_ms_stdev["gemini_all"] = float(gemini_all)
    if chatgpt_first:
        timings_ms_stdev["chatgpt_first"] = float(chatgpt_first)
    if chatgpt_all:
        timings_ms_stdev["chatgpt_all"] = float(chatgpt_all)
elif not timings_ms_stdev and algorithm == "vf3":
    def maybe_add_stdev(name: str, key: str) -> None:
        value = env.get(key, "")
        if value:
            timings_ms_stdev[name] = float(value)

    maybe_add_stdev("baseline_first", "VF3_BASE_FIRST_MS_STDEV")
    maybe_add_stdev("baseline_all", "VF3_BASE_ALL_MS_STDEV")
    maybe_add_stdev("gemini_first", "VF3_GEMINI_FIRST_MS_STDEV")
    maybe_add_stdev("gemini_all", "VF3_GEMINI_ALL_MS_STDEV")
    maybe_add_stdev("chatgpt_first", "VF3_CHATGPT_FIRST_MS_STDEV")
    maybe_add_stdev("chatgpt_all", "VF3_CHATGPT_ALL_MS_STDEV")
elif not timings_ms_stdev and algorithm == "subgraph":
    def maybe_add_stdev(name: str, key: str) -> None:
        value = env.get(key, "")
        if value:
            timings_ms_stdev[name] = float(value)

    maybe_add_stdev("vf3_baseline_first", "VF3_BASE_FIRST_MS_STDEV")
    maybe_add_stdev("vf3_baseline_all", "VF3_BASE_ALL_MS_STDEV")
    maybe_add_stdev("vf3_gemini_first", "VF3_GEMINI_FIRST_MS_STDEV")
    maybe_add_stdev("vf3_gemini_all", "VF3_GEMINI_ALL_MS_STDEV")
    maybe_add_stdev("vf3_chatgpt_first", "VF3_CHATGPT_FIRST_MS_STDEV")
    maybe_add_stdev("vf3_chatgpt_all", "VF3_CHATGPT_ALL_MS_STDEV")
    maybe_add_stdev("glasgow_baseline_first", "GLASGOW_FIRST_MS_STDEV")
    maybe_add_stdev("glasgow_baseline_all", "GLASGOW_ALL_MS_STDEV")
    maybe_add_stdev("glasgow_gemini_first", "GLASGOW_GEMINI_FIRST_MS_STDEV")
    maybe_add_stdev("glasgow_gemini_all", "GLASGOW_GEMINI_ALL_MS_STDEV")
    maybe_add_stdev("glasgow_chatgpt_first", "GLASGOW_CHATGPT_FIRST_MS_STDEV")
    maybe_add_stdev("glasgow_chatgpt_all", "GLASGOW_CHATGPT_ALL_MS_STDEV")
if timings_ms_stdev:
    data["timings_ms_stdev"] = timings_ms_stdev

memory_kb = parse_json_env("MEMORY_KB_JSON")
if not isinstance(memory_kb, dict):
    memory_kb = {}
if not memory_kb and algorithm == "dijkstra":
    baseline = env.get("DIJKSTRA_BASELINE_RSS_KB", "")
    llm = env.get("DIJKSTRA_LLM_RSS_KB", "")
    gemini = env.get("DIJKSTRA_GEMINI_RSS_KB", "")
    if baseline:
        try:
            memory_kb["baseline"] = int(baseline)
        except ValueError:
            pass
    if llm:
        try:
            memory_kb["llm"] = int(llm)
            memory_kb["chatgpt"] = int(llm)
        except ValueError:
            pass
    if gemini:
        try:
            memory_kb["gemini"] = int(gemini)
        except ValueError:
            pass
elif not memory_kb and algorithm == "glasgow":
    first = env.get("GLASGOW_FIRST_RSS_KB", "")
    all_kb = env.get("GLASGOW_ALL_RSS_KB", "")
    if first:
        try:
            memory_kb["first"] = int(first)
        except ValueError:
            pass
    if all_kb:
        try:
            memory_kb["all"] = int(all_kb)
        except ValueError:
            pass
    gemini_first = env.get("GLASGOW_GEMINI_FIRST_RSS_KB", "")
    gemini_all = env.get("GLASGOW_GEMINI_ALL_RSS_KB", "")
    chatgpt_first = env.get("GLASGOW_CHATGPT_FIRST_RSS_KB", "")
    chatgpt_all = env.get("GLASGOW_CHATGPT_ALL_RSS_KB", "")
    for key, value in (
        ("gemini_first", gemini_first),
        ("gemini_all", gemini_all),
        ("chatgpt_first", chatgpt_first),
        ("chatgpt_all", chatgpt_all),
    ):
        if value:
            try:
                memory_kb[key] = int(value)
            except ValueError:
                pass
elif not memory_kb and algorithm == "vf3":
    def maybe_add_int(name: str, key: str) -> None:
        value = env.get(key, "")
        if not value:
            return
        try:
            memory_kb[name] = int(value)
        except ValueError:
            return

    maybe_add_int("baseline_first", "VF3_BASE_FIRST_RSS_KB")
    maybe_add_int("baseline_all", "VF3_BASE_ALL_RSS_KB")
    maybe_add_int("gemini_first", "VF3_GEMINI_FIRST_RSS_KB")
    maybe_add_int("gemini_all", "VF3_GEMINI_ALL_RSS_KB")
    maybe_add_int("chatgpt_first", "VF3_CHATGPT_FIRST_RSS_KB")
    maybe_add_int("chatgpt_all", "VF3_CHATGPT_ALL_RSS_KB")
elif not memory_kb and algorithm == "subgraph":
    def maybe_add_int(name: str, key: str) -> None:
        value = env.get(key, "")
        if not value:
            return
        try:
            memory_kb[name] = int(value)
        except ValueError:
            return

    maybe_add_int("vf3_baseline_first", "VF3_BASE_FIRST_RSS_KB")
    maybe_add_int("vf3_baseline_all", "VF3_BASE_ALL_RSS_KB")
    maybe_add_int("vf3_gemini_first", "VF3_GEMINI_FIRST_RSS_KB")
    maybe_add_int("vf3_gemini_all", "VF3_GEMINI_ALL_RSS_KB")
    maybe_add_int("vf3_chatgpt_first", "VF3_CHATGPT_FIRST_RSS_KB")
    maybe_add_int("vf3_chatgpt_all", "VF3_CHATGPT_ALL_RSS_KB")
    maybe_add_int("glasgow_baseline_first", "GLASGOW_FIRST_RSS_KB")
    maybe_add_int("glasgow_baseline_all", "GLASGOW_ALL_RSS_KB")
    maybe_add_int("glasgow_gemini_first", "GLASGOW_GEMINI_FIRST_RSS_KB")
    maybe_add_int("glasgow_gemini_all", "GLASGOW_GEMINI_ALL_RSS_KB")
    maybe_add_int("glasgow_chatgpt_first", "GLASGOW_CHATGPT_FIRST_RSS_KB")
    maybe_add_int("glasgow_chatgpt_all", "GLASGOW_CHATGPT_ALL_RSS_KB")

if memory_kb:
    data["memory_kb"] = memory_kb

memory_kb_stdev = parse_json_env("MEMORY_KB_STDEV_JSON")
if not isinstance(memory_kb_stdev, dict):
    memory_kb_stdev = {}
if not memory_kb_stdev and algorithm == "dijkstra":
    baseline = env.get("DIJKSTRA_BASELINE_RSS_KB_STDEV", "")
    llm = env.get("DIJKSTRA_LLM_RSS_KB_STDEV", "")
    gemini = env.get("DIJKSTRA_GEMINI_RSS_KB_STDEV", "")
    if baseline:
        try:
            memory_kb_stdev["baseline"] = int(baseline)
        except ValueError:
            pass
    if llm:
        try:
            memory_kb_stdev["llm"] = int(llm)
            memory_kb_stdev["chatgpt"] = int(llm)
        except ValueError:
            pass
    if gemini:
        try:
            memory_kb_stdev["gemini"] = int(gemini)
        except ValueError:
            pass
elif not memory_kb_stdev and algorithm == "glasgow":
    first = env.get("GLASGOW_FIRST_RSS_KB_STDEV", "")
    all_kb = env.get("GLASGOW_ALL_RSS_KB_STDEV", "")
    if first:
        try:
            memory_kb_stdev["first"] = int(first)
        except ValueError:
            pass
    if all_kb:
        try:
            memory_kb_stdev["all"] = int(all_kb)
        except ValueError:
            pass
    gemini_first = env.get("GLASGOW_GEMINI_FIRST_RSS_KB_STDEV", "")
    gemini_all = env.get("GLASGOW_GEMINI_ALL_RSS_KB_STDEV", "")
    chatgpt_first = env.get("GLASGOW_CHATGPT_FIRST_RSS_KB_STDEV", "")
    chatgpt_all = env.get("GLASGOW_CHATGPT_ALL_RSS_KB_STDEV", "")
    for key, value in (
        ("gemini_first", gemini_first),
        ("gemini_all", gemini_all),
        ("chatgpt_first", chatgpt_first),
        ("chatgpt_all", chatgpt_all),
    ):
        if value:
            try:
                memory_kb_stdev[key] = int(value)
            except ValueError:
                pass
elif not memory_kb_stdev and algorithm == "vf3":
    def maybe_add_int_stdev(name: str, key: str) -> None:
        value = env.get(key, "")
        if not value:
            return
        try:
            memory_kb_stdev[name] = int(value)
        except ValueError:
            return

    maybe_add_int_stdev("baseline_first", "VF3_BASE_FIRST_RSS_KB_STDEV")
    maybe_add_int_stdev("baseline_all", "VF3_BASE_ALL_RSS_KB_STDEV")
    maybe_add_int_stdev("gemini_first", "VF3_GEMINI_FIRST_RSS_KB_STDEV")
    maybe_add_int_stdev("gemini_all", "VF3_GEMINI_ALL_RSS_KB_STDEV")
    maybe_add_int_stdev("chatgpt_first", "VF3_CHATGPT_FIRST_RSS_KB_STDEV")
    maybe_add_int_stdev("chatgpt_all", "VF3_CHATGPT_ALL_RSS_KB_STDEV")
elif not memory_kb_stdev and algorithm == "subgraph":
    def maybe_add_int_stdev(name: str, key: str) -> None:
        value = env.get(key, "")
        if not value:
            return
        try:
            memory_kb_stdev[name] = int(value)
        except ValueError:
            return

    maybe_add_int_stdev("vf3_baseline_first", "VF3_BASE_FIRST_RSS_KB_STDEV")
    maybe_add_int_stdev("vf3_baseline_all", "VF3_BASE_ALL_RSS_KB_STDEV")
    maybe_add_int_stdev("vf3_gemini_first", "VF3_GEMINI_FIRST_RSS_KB_STDEV")
    maybe_add_int_stdev("vf3_gemini_all", "VF3_GEMINI_ALL_RSS_KB_STDEV")
    maybe_add_int_stdev("vf3_chatgpt_first", "VF3_CHATGPT_FIRST_RSS_KB_STDEV")
    maybe_add_int_stdev("vf3_chatgpt_all", "VF3_CHATGPT_ALL_RSS_KB_STDEV")
    maybe_add_int_stdev("glasgow_baseline_first", "GLASGOW_FIRST_RSS_KB_STDEV")
    maybe_add_int_stdev("glasgow_baseline_all", "GLASGOW_ALL_RSS_KB_STDEV")
    maybe_add_int_stdev("glasgow_gemini_first", "GLASGOW_GEMINI_FIRST_RSS_KB_STDEV")
    maybe_add_int_stdev("glasgow_gemini_all", "GLASGOW_GEMINI_ALL_RSS_KB_STDEV")
    maybe_add_int_stdev("glasgow_chatgpt_first", "GLASGOW_CHATGPT_FIRST_RSS_KB_STDEV")
    maybe_add_int_stdev("glasgow_chatgpt_all", "GLASGOW_CHATGPT_ALL_RSS_KB_STDEV")

if memory_kb_stdev:
    data["memory_kb_stdev"] = memory_kb_stdev

def maybe_int_env(key: str):
    value = env.get(key, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None

dynamic_match_counts = parse_json_env("MATCH_COUNTS_JSON")
if isinstance(dynamic_match_counts, dict):
    data["match_counts"] = dynamic_match_counts

statistical_tests = parse_json_env("STATISTICAL_TESTS_JSON")
if isinstance(statistical_tests, dict):
    data["statistical_tests"] = statistical_tests

if not isinstance(dynamic_match_counts, dict) and algorithm == "dijkstra":
    chat_match = maybe_int_env("DIJKSTRA_CHATGPT_MATCH")
    chat_total = maybe_int_env("DIJKSTRA_CHATGPT_TOTAL")
    chat_mismatch = maybe_int_env("DIJKSTRA_CHATGPT_MISMATCH")
    if chat_match is None and chat_total is None and chat_mismatch is None:
        chat_match = maybe_int_env("DIJKSTRA_MATCH")
        chat_total = maybe_int_env("DIJKSTRA_TOTAL")
        chat_mismatch = maybe_int_env("DIJKSTRA_MISMATCH")
    gem_match = maybe_int_env("DIJKSTRA_GEMINI_MATCH")
    gem_total = maybe_int_env("DIJKSTRA_GEMINI_TOTAL")
    gem_mismatch = maybe_int_env("DIJKSTRA_GEMINI_MISMATCH")
    if any(v is not None for v in (chat_match, chat_total, chat_mismatch, gem_match, gem_total, gem_mismatch)):
        data["match_counts"] = {
            "chatgpt": {
                "matches": chat_match,
                "total": chat_total,
                "mismatches": chat_mismatch,
            },
            "gemini": {
                "matches": gem_match,
                "total": gem_total,
                "mismatches": gem_mismatch,
            },
        }

if not isinstance(dynamic_match_counts, dict) and algorithm == "glasgow":
    baseline_success = maybe_int_env("GLASGOW_BASELINE_SUCCESS")
    baseline_failed = maybe_int_env("GLASGOW_BASELINE_FAILED")
    chat_match = maybe_int_env("GLASGOW_CHATGPT_MATCH")
    chat_total = maybe_int_env("GLASGOW_CHATGPT_TOTAL")
    chat_mismatch = maybe_int_env("GLASGOW_CHATGPT_MISMATCH")
    gem_match = maybe_int_env("GLASGOW_GEMINI_MATCH")
    gem_total = maybe_int_env("GLASGOW_GEMINI_TOTAL")
    gem_mismatch = maybe_int_env("GLASGOW_GEMINI_MISMATCH")
    if any(
        v is not None
        for v in (
            baseline_success,
            baseline_failed,
            chat_match,
            chat_total,
            chat_mismatch,
            gem_match,
            gem_total,
            gem_mismatch,
        )
    ):
        data["match_counts"] = {
            "baseline": {
                "success": baseline_success,
                "failed": baseline_failed,
            },
            "chatgpt": {
                "matches": chat_match,
                "total": chat_total,
                "mismatches": chat_mismatch,
            },
            "gemini": {
                "matches": gem_match,
                "total": gem_total,
                "mismatches": gem_mismatch,
            },
        }

if not isinstance(dynamic_match_counts, dict) and algorithm == "vf3":
    baseline_success = maybe_int_env("VF3_BASELINE_SUCCESS")
    baseline_failed = maybe_int_env("VF3_BASELINE_FAILED")
    chat_match = maybe_int_env("VF3_CHATGPT_MATCH")
    chat_total = maybe_int_env("VF3_CHATGPT_TOTAL")
    chat_mismatch = maybe_int_env("VF3_CHATGPT_MISMATCH")
    gem_match = maybe_int_env("VF3_GEMINI_MATCH")
    gem_total = maybe_int_env("VF3_GEMINI_TOTAL")
    gem_mismatch = maybe_int_env("VF3_GEMINI_MISMATCH")
    if any(
        v is not None
        for v in (
            baseline_success,
            baseline_failed,
            chat_match,
            chat_total,
            chat_mismatch,
            gem_match,
            gem_total,
            gem_mismatch,
        )
    ):
        data["match_counts"] = {
            "baseline": {
                "success": baseline_success,
                "failed": baseline_failed,
            },
            "chatgpt": {
                "matches": chat_match,
                "total": chat_total,
                "mismatches": chat_mismatch,
            },
            "gemini": {
                "matches": gem_match,
                "total": gem_total,
                "mismatches": gem_mismatch,
            },
        }
if not isinstance(dynamic_match_counts, dict) and algorithm == "subgraph":
    vf3_success = maybe_int_env("VF3_BASELINE_SUCCESS")
    vf3_failed = maybe_int_env("VF3_BASELINE_FAILED")
    vf3_chat_match = maybe_int_env("VF3_CHATGPT_MATCH")
    vf3_chat_total = maybe_int_env("VF3_CHATGPT_TOTAL")
    vf3_chat_mismatch = maybe_int_env("VF3_CHATGPT_MISMATCH")
    vf3_gem_match = maybe_int_env("VF3_GEMINI_MATCH")
    vf3_gem_total = maybe_int_env("VF3_GEMINI_TOTAL")
    vf3_gem_mismatch = maybe_int_env("VF3_GEMINI_MISMATCH")
    glasgow_success = maybe_int_env("GLASGOW_BASELINE_SUCCESS")
    glasgow_failed = maybe_int_env("GLASGOW_BASELINE_FAILED")
    glasgow_match = maybe_int_env("GLASGOW_BASELINE_MATCH")
    glasgow_total = maybe_int_env("GLASGOW_BASELINE_TOTAL")
    glasgow_mismatch = maybe_int_env("GLASGOW_BASELINE_MISMATCH")
    glasgow_chat_match = maybe_int_env("GLASGOW_CHATGPT_MATCH")
    glasgow_chat_total = maybe_int_env("GLASGOW_CHATGPT_TOTAL")
    glasgow_chat_mismatch = maybe_int_env("GLASGOW_CHATGPT_MISMATCH")
    glasgow_gem_match = maybe_int_env("GLASGOW_GEMINI_MATCH")
    glasgow_gem_total = maybe_int_env("GLASGOW_GEMINI_TOTAL")
    glasgow_gem_mismatch = maybe_int_env("GLASGOW_GEMINI_MISMATCH")
    if any(
        v is not None
        for v in (
            vf3_success,
            vf3_failed,
            vf3_chat_match,
            vf3_chat_total,
            vf3_chat_mismatch,
            vf3_gem_match,
            vf3_gem_total,
            vf3_gem_mismatch,
            glasgow_success,
            glasgow_failed,
            glasgow_match,
            glasgow_total,
            glasgow_mismatch,
            glasgow_chat_match,
            glasgow_chat_total,
            glasgow_chat_mismatch,
            glasgow_gem_match,
            glasgow_gem_total,
            glasgow_gem_mismatch,
        )
    ):
        data["match_counts"] = {
            "vf3_baseline": {
                "success": vf3_success,
                "failed": vf3_failed,
            },
            "vf3_chatgpt": {
                "matches": vf3_chat_match,
                "total": vf3_chat_total,
                "mismatches": vf3_chat_mismatch,
            },
            "vf3_gemini": {
                "matches": vf3_gem_match,
                "total": vf3_gem_total,
                "mismatches": vf3_gem_mismatch,
            },
            "glasgow_baseline": {
                "success": glasgow_success,
                "failed": glasgow_failed,
                "matches": glasgow_match,
                "total": glasgow_total,
                "mismatches": glasgow_mismatch,
            },
            "glasgow_chatgpt": {
                "matches": glasgow_chat_match,
                "total": glasgow_chat_total,
                "mismatches": glasgow_chat_mismatch,
            },
            "glasgow_gemini": {
                "matches": glasgow_gem_match,
                "total": glasgow_gem_total,
                "mismatches": glasgow_gem_mismatch,
            },
        }
if algorithm == "subgraph" and env.get("SUBGRAPH_PHASE", "").strip().lower() == "glasgow":
    for key in ("timings_ms", "timings_ms_stdev", "memory_kb", "memory_kb_stdev"):
        if key in data and isinstance(data[key], dict):
            data[key] = {k: v for k, v in data[key].items() if not k.startswith("vf3_")}
    if "match_counts" in data and isinstance(data["match_counts"], dict):
        data["match_counts"] = {
            k: v for k, v in data["match_counts"].items() if not k.startswith("vf3_")
        }
    existing_path = Path("outputs/result.json")
    if existing_path.exists():
        try:
            previous = json.loads(existing_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if isinstance(previous, dict):
            # Preserve phase-1 visualization and append text output for the combined UI.
            if "visualization" in previous and "visualization" not in data:
                data["visualization"] = previous["visualization"]
                data.pop("visualization_error", None)
            if previous.get("output") and data.get("output"):
                prev_out = str(previous.get("output", "")).rstrip()
                new_out = str(data.get("output", "")).lstrip()
                if prev_out and new_out:
                    data["output"] = prev_out + "\n\n" + new_out
            elif previous.get("output") and not data.get("output"):
                data["output"] = previous.get("output")
            if previous.get("visualization_error") and "visualization" not in data and "visualization_error" not in data:
                data["visualization_error"] = previous.get("visualization_error")
            for key in ("timings_ms", "timings_ms_stdev", "memory_kb", "memory_kb_stdev", "match_counts"):
                if key in previous:
                    merged = dict(previous.get(key, {}))
                    merged.update(data.get(key, {}))
                    data[key] = merged
            if "statistical_tests" in previous or "statistical_tests" in data:
                data["statistical_tests"] = merge_statistical_tests(
                    previous.get("statistical_tests"),
                    data.get("statistical_tests"),
                )
            if isinstance(previous.get("variant_metadata"), list) or isinstance(data.get("variant_metadata"), list):
                merged_meta = []
                seen_variant_ids = set()
                for row in list(previous.get("variant_metadata") or []) + list(data.get("variant_metadata") or []):
                    if not isinstance(row, dict):
                        continue
                    variant_id = str(row.get("variant_id") or "").strip()
                    if not variant_id:
                        continue
                    if variant_id in seen_variant_ids:
                        continue
                    seen_variant_ids.add(variant_id)
                    merged_meta.append(row)
                if merged_meta:
                    data["variant_metadata"] = merged_meta
            if "equivalence_check" in previous and "equivalence_check" not in data:
                data["equivalence_check"] = previous.get("equivalence_check")
            elif "equivalence_check" in previous and "equivalence_check" in data:
                prev_eq = previous.get("equivalence_check")
                cur_eq = data.get("equivalence_check")
                if isinstance(prev_eq, dict) and isinstance(cur_eq, dict):
                    prev_records = prev_eq.get("records") if isinstance(prev_eq.get("records"), list) else []
                    cur_records = cur_eq.get("records") if isinstance(cur_eq.get("records"), list) else []
                    merged_records = []
                    seen = set()
                    for rec in prev_records + cur_records:
                        try:
                            key = json.dumps(rec, sort_keys=True)
                        except TypeError:
                            key = str(rec)
                        if key in seen:
                            continue
                        seen.add(key)
                        merged_records.append(rec)
                    selected = [r for r in merged_records if isinstance(r, dict) and bool(r.get("selected_for_solver"))]
                    selected_failures = [r for r in selected if not bool(r.get("equivalent"))]
                    data["equivalence_check"] = {
                        "applies": True,
                        "records": merged_records,
                        "selected_for_solver_count": len(selected),
                        "selected_for_solver_failures": len(selected_failures),
                        "graphs_not_mathematically_identical": len(selected_failures) > 0,
                    }
            if "subgraph_phase" in previous and data.get("subgraph_phase") == "glasgow":
                data["subgraph_phase_prev"] = previous.get("subgraph_phase")
Path("outputs/result.json").write_text(
    json.dumps(data, indent=2) + "\n", encoding="utf-8"
)
