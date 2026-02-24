import datetime
import json
import os
from pathlib import Path

algorithm = os.environ.get("ALGORITHM_INPUT", "")
exit_code = os.environ.get("EXIT_CODE", "")
request_id = os.environ.get("REQUEST_ID_INPUT", "")
timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
input_mode = os.environ.get("INPUT_MODE_INPUT", "")
input_files = os.environ.get("INPUT_FILES_INPUT", "")
gen_n = os.environ.get("GENERATOR_N_INPUT", "")
gen_k = os.environ.get("GENERATOR_K_INPUT", "")
gen_density = os.environ.get("GENERATOR_DENSITY_INPUT", "")
seed_used = os.environ.get("SEED_USED", "")

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
if inputs:
    data["inputs"] = inputs
iterations = os.environ.get("ITERATIONS", "").strip()
if iterations:
    try:
        data["iterations"] = int(iterations)
    except ValueError:
        pass
warmup = os.environ.get("WARMUP", "").strip()
if warmup:
    try:
        data["warmup"] = int(warmup)
    except ValueError:
        pass
duration_ms = os.environ.get("RUN_DURATION_MS", "").strip()
if duration_ms:
    try:
        data["run_duration_ms"] = float(duration_ms)
    except ValueError:
        pass
timings_ms = {}
if algorithm == "dijkstra":
    baseline = os.environ.get("DIJKSTRA_BASELINE_MS", "")
    llm = os.environ.get("DIJKSTRA_LLM_MS", "")
    gemini = os.environ.get("DIJKSTRA_GEMINI_MS", "")
    if baseline:
        timings_ms["baseline"] = float(baseline)
    if llm:
        timings_ms["llm"] = float(llm)
        timings_ms["chatgpt"] = float(llm)
    if gemini:
        timings_ms["gemini"] = float(gemini)
elif algorithm == "glasgow":
    first = os.environ.get("GLASGOW_FIRST_MS", "")
    all_ms = os.environ.get("GLASGOW_ALL_MS", "")
    if first:
        timings_ms["first"] = float(first)
    if all_ms:
        timings_ms["all"] = float(all_ms)
    gemini_first = os.environ.get("GLASGOW_GEMINI_FIRST_MS", "")
    gemini_all = os.environ.get("GLASGOW_GEMINI_ALL_MS", "")
    chatgpt_first = os.environ.get("GLASGOW_CHATGPT_FIRST_MS", "")
    chatgpt_all = os.environ.get("GLASGOW_CHATGPT_ALL_MS", "")
    if gemini_first:
        timings_ms["gemini_first"] = float(gemini_first)
    if gemini_all:
        timings_ms["gemini_all"] = float(gemini_all)
    if chatgpt_first:
        timings_ms["chatgpt_first"] = float(chatgpt_first)
    if chatgpt_all:
        timings_ms["chatgpt_all"] = float(chatgpt_all)
elif algorithm == "vf3":
    def maybe_add(name: str, key: str) -> None:
        value = os.environ.get(key, "")
        if value:
            timings_ms[name] = float(value)

    maybe_add("baseline_first", "VF3_BASE_FIRST_MS")
    maybe_add("baseline_all", "VF3_BASE_ALL_MS")
    maybe_add("gemini_first", "VF3_GEMINI_FIRST_MS")
    maybe_add("gemini_all", "VF3_GEMINI_ALL_MS")
    maybe_add("chatgpt_first", "VF3_CHATGPT_FIRST_MS")
    maybe_add("chatgpt_all", "VF3_CHATGPT_ALL_MS")
elif algorithm == "subgraph":
    def maybe_add(name: str, key: str) -> None:
        value = os.environ.get(key, "")
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
    phase = os.environ.get("SUBGRAPH_PHASE", "").strip().lower()
    data["subgraph_phase"] = phase or "full"
if timings_ms:
    data["timings_ms"] = timings_ms

timings_ms_stdev = {}
if algorithm == "dijkstra":
    baseline = os.environ.get("DIJKSTRA_BASELINE_MS_STDEV", "")
    llm = os.environ.get("DIJKSTRA_LLM_MS_STDEV", "")
    gemini = os.environ.get("DIJKSTRA_GEMINI_MS_STDEV", "")
    if baseline:
        timings_ms_stdev["baseline"] = float(baseline)
    if llm:
        timings_ms_stdev["llm"] = float(llm)
        timings_ms_stdev["chatgpt"] = float(llm)
    if gemini:
        timings_ms_stdev["gemini"] = float(gemini)
elif algorithm == "glasgow":
    first = os.environ.get("GLASGOW_FIRST_MS_STDEV", "")
    all_ms = os.environ.get("GLASGOW_ALL_MS_STDEV", "")
    if first:
        timings_ms_stdev["first"] = float(first)
    if all_ms:
        timings_ms_stdev["all"] = float(all_ms)
    gemini_first = os.environ.get("GLASGOW_GEMINI_FIRST_MS_STDEV", "")
    gemini_all = os.environ.get("GLASGOW_GEMINI_ALL_MS_STDEV", "")
    chatgpt_first = os.environ.get("GLASGOW_CHATGPT_FIRST_MS_STDEV", "")
    chatgpt_all = os.environ.get("GLASGOW_CHATGPT_ALL_MS_STDEV", "")
    if gemini_first:
        timings_ms_stdev["gemini_first"] = float(gemini_first)
    if gemini_all:
        timings_ms_stdev["gemini_all"] = float(gemini_all)
    if chatgpt_first:
        timings_ms_stdev["chatgpt_first"] = float(chatgpt_first)
    if chatgpt_all:
        timings_ms_stdev["chatgpt_all"] = float(chatgpt_all)
elif algorithm == "vf3":
    def maybe_add_stdev(name: str, key: str) -> None:
        value = os.environ.get(key, "")
        if value:
            timings_ms_stdev[name] = float(value)

    maybe_add_stdev("baseline_first", "VF3_BASE_FIRST_MS_STDEV")
    maybe_add_stdev("baseline_all", "VF3_BASE_ALL_MS_STDEV")
    maybe_add_stdev("gemini_first", "VF3_GEMINI_FIRST_MS_STDEV")
    maybe_add_stdev("gemini_all", "VF3_GEMINI_ALL_MS_STDEV")
    maybe_add_stdev("chatgpt_first", "VF3_CHATGPT_FIRST_MS_STDEV")
    maybe_add_stdev("chatgpt_all", "VF3_CHATGPT_ALL_MS_STDEV")
elif algorithm == "subgraph":
    def maybe_add_stdev(name: str, key: str) -> None:
        value = os.environ.get(key, "")
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

memory_kb = {}
if algorithm == "dijkstra":
    baseline = os.environ.get("DIJKSTRA_BASELINE_RSS_KB", "")
    llm = os.environ.get("DIJKSTRA_LLM_RSS_KB", "")
    gemini = os.environ.get("DIJKSTRA_GEMINI_RSS_KB", "")
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
elif algorithm == "glasgow":
    first = os.environ.get("GLASGOW_FIRST_RSS_KB", "")
    all_kb = os.environ.get("GLASGOW_ALL_RSS_KB", "")
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
    gemini_first = os.environ.get("GLASGOW_GEMINI_FIRST_RSS_KB", "")
    gemini_all = os.environ.get("GLASGOW_GEMINI_ALL_RSS_KB", "")
    chatgpt_first = os.environ.get("GLASGOW_CHATGPT_FIRST_RSS_KB", "")
    chatgpt_all = os.environ.get("GLASGOW_CHATGPT_ALL_RSS_KB", "")
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
elif algorithm == "vf3":
    def maybe_add_int(name: str, key: str) -> None:
        value = os.environ.get(key, "")
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
elif algorithm == "subgraph":
    def maybe_add_int(name: str, key: str) -> None:
        value = os.environ.get(key, "")
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

memory_kb_stdev = {}
if algorithm == "dijkstra":
    baseline = os.environ.get("DIJKSTRA_BASELINE_RSS_KB_STDEV", "")
    llm = os.environ.get("DIJKSTRA_LLM_RSS_KB_STDEV", "")
    gemini = os.environ.get("DIJKSTRA_GEMINI_RSS_KB_STDEV", "")
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
elif algorithm == "glasgow":
    first = os.environ.get("GLASGOW_FIRST_RSS_KB_STDEV", "")
    all_kb = os.environ.get("GLASGOW_ALL_RSS_KB_STDEV", "")
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
    gemini_first = os.environ.get("GLASGOW_GEMINI_FIRST_RSS_KB_STDEV", "")
    gemini_all = os.environ.get("GLASGOW_GEMINI_ALL_RSS_KB_STDEV", "")
    chatgpt_first = os.environ.get("GLASGOW_CHATGPT_FIRST_RSS_KB_STDEV", "")
    chatgpt_all = os.environ.get("GLASGOW_CHATGPT_ALL_RSS_KB_STDEV", "")
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
elif algorithm == "vf3":
    def maybe_add_int_stdev(name: str, key: str) -> None:
        value = os.environ.get(key, "")
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
elif algorithm == "subgraph":
    def maybe_add_int_stdev(name: str, key: str) -> None:
        value = os.environ.get(key, "")
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
    value = os.environ.get(key, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None

if algorithm == "dijkstra":
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

if algorithm == "glasgow":
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

if algorithm == "vf3":
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
if algorithm == "subgraph":
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
if algorithm == "subgraph" and os.environ.get("SUBGRAPH_PHASE", "").strip().lower() == "glasgow":
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
            if "subgraph_phase" in previous and data.get("subgraph_phase") == "glasgow":
                data["subgraph_phase_prev"] = previous.get("subgraph_phase")
Path("outputs/result.json").write_text(
    json.dumps(data, indent=2) + "\n", encoding="utf-8"
)
