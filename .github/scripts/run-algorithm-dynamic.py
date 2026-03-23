#!/usr/bin/env python3
"""Dynamic GitHub benchmark runner using discovered solver variants."""

from __future__ import annotations

import json
import os
import random
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = REPO_ROOT / "outputs"
RESULT_TEXT_PATH = OUTPUTS_DIR / "result.txt"
METRICS_PATH = OUTPUTS_DIR / "run_metrics.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_solver_discovery_module():
    module_path = REPO_ROOT / "scripts" / "solver_discovery.py"
    spec = importlib.util.spec_from_file_location("solver_discovery", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load solver discovery module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_int_env(name: str, default: int, minimum: int | None = None) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def parse_float_env(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def parse_last_line_paths(raw: str) -> list[str]:
    lines = [line.strip() for line in str(raw or "").splitlines() if line.strip()]
    if not lines:
        return []
    return [part.strip() for part in lines[-1].split(",") if part.strip()]


def median_and_stdev(samples: list[float]) -> tuple[float | None, float]:
    if not samples:
        return None, 0.0
    if len(samples) == 1:
        return float(samples[0]), 0.0
    return float(statistics.median(samples)), float(statistics.stdev(samples))


def parse_solution_count(text: str) -> int | None:
    src = str(text or "").strip()
    if not src:
        return None
    patterns = [
        r"(?im)\bsolutions?\s*(?:count|found|total)?\s*[:=]\s*(-?\d+)\b",
        r"(?im)\bcount\s*[:=]\s*(-?\d+)\b",
        r"(?im)\b(-?\d+)\s+solutions?\b",
        r"(?im)\bmatches?\s*[:=]\s*(-?\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, src)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    lines = [line.strip() for line in src.splitlines() if line.strip()]
    if len(lines) == 1 and re.fullmatch(r"-?\d+", lines[0]):
        return int(lines[0])
    return None


def normalize_dijkstra_output(text: str) -> str:
    lines = [line.strip() for line in str(text or "").replace("\r", "").split("\n")]
    cleaned = []
    for line in lines:
        if not line:
            continue
        if line.lower().startswith("runtime"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


@dataclass(frozen=True)
class SolverRow:
    variant_id: str
    family: str
    algorithm: str
    role: str
    label: str
    llm_key: str | None
    llm_label: str | None
    binary_path: str


def load_solver_rows() -> list[SolverRow]:
    manifest_path = OUTPUTS_DIR / "solver_variants.json"
    rows = None
    if manifest_path.is_file():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            rows = payload.get("solvers")
        except (OSError, json.JSONDecodeError):
            rows = None
    if not isinstance(rows, list):
        solver_discovery = load_solver_discovery_module()
        catalog = solver_discovery.build_catalog(REPO_ROOT)
        rows = catalog.get("solvers", [])

    result: list[SolverRow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        variant_id = str(row.get("variant_id") or "").strip()
        family = str(row.get("family") or "").strip().lower()
        algorithm = str(row.get("algorithm") or "").strip().lower()
        role = str(row.get("role") or "").strip().lower() or "variant"
        binary_path = str(row.get("binary_path") or "").strip()
        if not variant_id or family not in {"dijkstra", "vf3", "glasgow"}:
            continue
        if not binary_path:
            if role == "baseline":
                if family == "dijkstra":
                    binary_path = "baselines/dijkstra"
                elif family == "vf3":
                    binary_path = "baselines/vf3lib/bin/vf3"
                else:
                    binary_path = "baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver"
            else:
                binary_path = f"src/{variant_id}"
        result.append(
            SolverRow(
                variant_id=variant_id,
                family=family,
                algorithm=algorithm or ("dijkstra" if family == "dijkstra" else family),
                role=role,
                label=str(row.get("label") or variant_id),
                llm_key=(str(row.get("llm_key") or "").strip().lower() or None),
                llm_label=(str(row.get("llm_label") or "").strip() or None),
                binary_path=binary_path,
            )
        )
    result.sort(key=lambda row: (row.family, row.role != "baseline", row.label.lower()))
    return result


def resolve_binary(path_str: str) -> Path:
    candidate = (REPO_ROOT / path_str).resolve()
    if candidate.is_file():
        return candidate
    exe = candidate.with_suffix(candidate.suffix + ".exe")
    if exe.is_file():
        return exe
    legacy_fallbacks = {
        "src/dijkstra_chatgpt": ["src/dijkstra_llm"],
        "src/vf3_chatgpt": ["src/chatvf3"],
        "src/vf3_gemini": ["src/vf3"],
    }
    for fallback in legacy_fallbacks.get(path_str, []):
        fp = (REPO_ROOT / fallback).resolve()
        if fp.is_file():
            return fp
        fexe = fp.with_suffix(fp.suffix + ".exe")
        if fexe.is_file():
            return fexe
    raise FileNotFoundError(f"Missing solver binary: {path_str}")


def try_resolve_binary(path_str: str) -> Path | None:
    try:
        return resolve_binary(path_str)
    except FileNotFoundError:
        return None


def run_with_peak_rss(command: list[str]) -> tuple[float, int, str, str, int]:
    def read_rss_bytes(pid: int) -> int:
        status_path = Path(f"/proc/{pid}/status")
        if not status_path.is_file():
            return 0
        try:
            for line in status_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.startswith("VmRSS:"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    return 0
                return max(0, int(parts[1])) * 1024
        except Exception:
            return 0
        return 0

    started = time.perf_counter()
    proc = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    peak = 0
    while proc.poll() is None:
        rss = read_rss_bytes(proc.pid)
        if rss > peak:
            peak = rss
        time.sleep(0.005)
    stdout, stderr = proc.communicate()
    rss = read_rss_bytes(proc.pid)
    if rss > peak:
        peak = rss
    ended = time.perf_counter()
    duration_ms = max(0.0, (ended - started) * 1000.0)
    peak_kb = max(0, int(round(peak / 1024.0)))
    return duration_ms, peak_kb, stdout, stderr, int(proc.returncode)


def generate_inputs_for_iteration(
    algorithm: str,
    iteration_index: int,
    n: int,
    k: int,
    density: float,
    base_seed: int,
) -> dict[str, Path]:
    out_dir = OUTPUTS_DIR / "generated" / algorithm / f"iter_{iteration_index + 1}"
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = base_seed + iteration_index
    if algorithm == "dijkstra":
        cmd = [
            sys.executable,
            "utilities/generate_graphs.py",
            "--algorithm",
            "dijkstra",
            "--n",
            str(n),
            "--density",
            str(density),
            "--seed",
            str(seed),
            "--out-dir",
            str(out_dir),
        ]
        done = subprocess.run(cmd, cwd=str(REPO_ROOT), check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        paths = parse_last_line_paths(done.stdout)
        if not paths:
            raise RuntimeError("Generator did not return Dijkstra input path")
        return {"seed": Path(str(seed)), "dijkstra": Path(paths[0]).resolve()}

    cmd = [
        sys.executable,
        "utilities/generate_graphs.py",
        "--algorithm",
        "subgraph",
        "--n",
        str(n),
        "--k",
        str(k),
        "--density",
        str(density),
        "--seed",
        str(seed),
        "--out-dir",
        str(out_dir),
    ]
    done = subprocess.run(cmd, cwd=str(REPO_ROOT), check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    paths = parse_last_line_paths(done.stdout)
    if len(paths) < 4:
        raise RuntimeError("Generator did not return subgraph paths")
    lad_pattern, lad_target, vf_pattern, vf_target = [Path(p).resolve() for p in paths[:4]]
    return {
        "seed": Path(str(seed)),
        "lad_pattern": lad_pattern,
        "lad_target": lad_target,
        "vf_pattern": vf_pattern,
        "vf_target": vf_target,
    }


def get_premade_inputs(algorithm: str, input_files: list[str]) -> dict[str, Path]:
    files = [Path(item).resolve() for item in input_files if item]
    if algorithm == "dijkstra":
        if len(files) < 1:
            raise RuntimeError("Dijkstra requires one input file")
        return {"seed": Path(""), "dijkstra": files[0]}
    if len(files) < 2:
        raise RuntimeError(f"{algorithm} requires two input files")
    return {
        "seed": Path(""),
        "lad_pattern": files[0],
        "lad_target": files[1],
        "vf_pattern": files[0],
        "vf_target": files[1],
    }


def build_variant_metric_key(row: SolverRow) -> str:
    if row.role == "baseline":
        return "baseline"
    if row.llm_key:
        return row.llm_key
    tail = row.variant_id.split("_", 1)[-1].strip().lower()
    return tail or row.variant_id.lower()


def make_command(row: SolverRow, inputs: dict[str, Path]) -> list[str]:
    binary_path = Path(row.binary_path)
    if binary_path.is_absolute():
        binary = binary_path
    else:
        binary = resolve_binary(row.binary_path)
    if row.family == "dijkstra":
        return [str(binary), str(inputs["dijkstra"])]
    if row.family == "vf3":
        if row.role == "baseline":
            return [str(binary), "-u", "-r", "0", "-e", str(inputs["vf_pattern"]), str(inputs["vf_target"])]
        return [str(binary), "--non-induced", str(inputs["vf_pattern"]), str(inputs["vf_target"])]
    if row.family == "glasgow":
        if row.role == "baseline":
            return [str(binary), "--count-solutions", "--format", "vertexlabelledlad", str(inputs["lad_pattern"]), str(inputs["lad_target"])]
        return [str(binary), str(inputs["lad_pattern"]), str(inputs["lad_target"])]
    raise RuntimeError(f"Unsupported family: {row.family}")


def main() -> int:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    algorithm_input = str(os.environ.get("ALGORITHM_INPUT", "dijkstra") or "dijkstra").strip().lower()
    subgraph_phase = str(os.environ.get("SUBGRAPH_PHASE_INPUT", "") or "").strip().lower()
    input_mode = str(os.environ.get("INPUT_MODE_INPUT", "generate") or "generate").strip().lower()
    request_id = str(os.environ.get("REQUEST_ID_INPUT", "") or "").strip()
    iterations = parse_int_env("ITERATIONS_INPUT", 1, minimum=1)
    warmup = parse_int_env("WARMUP_INPUT", 0, minimum=0)
    n = parse_int_env("GENERATOR_N_INPUT", 100, minimum=2)
    k = parse_int_env("GENERATOR_K_INPUT", 10, minimum=1)
    density = parse_float_env("GENERATOR_DENSITY_INPUT", 0.01, minimum=0.000001, maximum=1.0)

    seed_raw = str(os.environ.get("GENERATOR_SEED_INPUT", "") or "").strip()
    if seed_raw:
        try:
            base_seed = int(seed_raw)
        except ValueError:
            base_seed = int(time.time() * 1000) & 0x7FFFFFFF
    else:
        base_seed = random.randint(1, 2_000_000_000)

    selected_family = algorithm_input
    if algorithm_input == "subgraph":
        if subgraph_phase in {"vf3", "glasgow"}:
            selected_family = subgraph_phase
        else:
            selected_family = "vf3"
            subgraph_phase = "vf3"

    exit_code = 0
    started = time.perf_counter()
    timings_ms: dict[str, float] = {}
    timings_ms_stdev: dict[str, float] = {}
    memory_kb: dict[str, int] = {}
    memory_kb_stdev: dict[str, int] = {}
    match_counts: dict[str, dict] = {}
    variant_metadata: list[dict] = []
    output_lines: list[str] = []

    try:
        rows = [row for row in load_solver_rows() if row.family == selected_family]
        if not rows:
            raise RuntimeError(f"No discovered solver rows for family '{selected_family}'.")

        by_role = sorted(rows, key=lambda row: (row.role != "baseline", row.label.lower()))
        baseline_row = next((row for row in by_role if row.role == "baseline"), None)
        if baseline_row is None:
            raise RuntimeError(f"No baseline solver for family '{selected_family}'.")

        # Resolve binaries once up front:
        # - baseline is mandatory
        # - non-baseline LLM variants are optional and skipped if their binary is absent
        available_rows: list[SolverRow] = []
        skipped_rows: list[str] = []
        for row in by_role:
            resolved = try_resolve_binary(row.binary_path)
            if resolved is None:
                if row.role == "baseline":
                    raise RuntimeError(
                        "Missing baseline solver binary: "
                        f"{row.binary_path}. Ensure 'Build Binaries' succeeded for this exact commit, "
                        "then rerun 'Run Algorithm'."
                    )
                skipped_rows.append(f"{row.label} ({row.binary_path})")
                continue
            available_rows.append(
                SolverRow(
                    variant_id=row.variant_id,
                    family=row.family,
                    algorithm=row.algorithm,
                    role=row.role,
                    label=row.label,
                    llm_key=row.llm_key,
                    llm_label=row.llm_label,
                    binary_path=str(resolved),
                )
            )

        by_role = sorted(available_rows, key=lambda row: (row.role != "baseline", row.label.lower()))
        baseline_row = next((row for row in by_role if row.role == "baseline"), None)
        if baseline_row is None:
            raise RuntimeError(
                f"No runnable baseline solver for family '{selected_family}' after binary resolution."
            )

        input_files_raw = str(os.environ.get("INPUT_FILES_INPUT", "") or "").strip()
        input_files = [part.strip() for part in input_files_raw.split(",") if part.strip()]

        per_solver_times: dict[str, list[float]] = {row.variant_id: [] for row in by_role}
        per_solver_mem: dict[str, list[int]] = {row.variant_id: [] for row in by_role}
        per_solver_outputs: dict[str, list[str]] = {row.variant_id: [] for row in by_role}

        for iter_idx in range(iterations):
            if input_mode == "generate":
                inputs = generate_inputs_for_iteration(
                    algorithm=algorithm_input if algorithm_input == "dijkstra" else "subgraph",
                    iteration_index=iter_idx,
                    n=n,
                    k=k,
                    density=density,
                    base_seed=base_seed,
                )
            else:
                inputs = get_premade_inputs(selected_family, input_files)

            for row in by_role:
                command = make_command(row, inputs)
                if iter_idx == 0:
                    for _ in range(warmup):
                        dur_ms, peak_kb, stdout, stderr, rc = run_with_peak_rss(command)
                        if rc != 0:
                            raise RuntimeError(f"Warmup failed for {row.variant_id}: code={rc} stderr={stderr[:300]}")
                dur_ms, peak_kb, stdout, stderr, rc = run_with_peak_rss(command)
                if rc != 0:
                    raise RuntimeError(f"{row.variant_id} failed: code={rc} stderr={stderr[:600]}")
                per_solver_times[row.variant_id].append(dur_ms)
                per_solver_mem[row.variant_id].append(peak_kb)
                per_solver_outputs[row.variant_id].append((stdout or "") + ("\n" + stderr if stderr else ""))

        baseline_key = build_variant_metric_key(baseline_row)
        for row in by_role:
            key = build_variant_metric_key(row)
            median_ms, stdev_ms = median_and_stdev(per_solver_times[row.variant_id])
            median_kb, stdev_kb = median_and_stdev([float(v) for v in per_solver_mem[row.variant_id]])
            if selected_family == "dijkstra":
                metric_key = key
                if median_ms is not None:
                    timings_ms[metric_key] = float(median_ms)
                    timings_ms_stdev[metric_key] = float(stdev_ms)
                if median_kb is not None:
                    memory_kb[metric_key] = int(round(median_kb))
                    memory_kb_stdev[metric_key] = int(round(stdev_kb))
                if row.variant_id == "dijkstra_chatgpt":
                    if metric_key in timings_ms:
                        timings_ms["llm"] = timings_ms[metric_key]
                        timings_ms["chatgpt"] = timings_ms[metric_key]
                        timings_ms_stdev["llm"] = timings_ms_stdev[metric_key]
                        timings_ms_stdev["chatgpt"] = timings_ms_stdev[metric_key]
                    if metric_key in memory_kb:
                        memory_kb["llm"] = memory_kb[metric_key]
                        memory_kb["chatgpt"] = memory_kb[metric_key]
                        memory_kb_stdev["llm"] = memory_kb_stdev[metric_key]
                        memory_kb_stdev["chatgpt"] = memory_kb_stdev[metric_key]
                variant_metadata.append(
                    {
                        "variant_id": row.variant_id,
                        "family": row.family,
                        "role": row.role,
                        "label": row.label,
                        "llm_key": row.llm_key,
                        "llm_label": row.llm_label,
                        "timing_key": metric_key,
                        "memory_key": metric_key,
                    }
                )
            else:
                prefix = key
                if algorithm_input == "subgraph":
                    prefix = f"{selected_family}_{prefix}"
                key_first = f"{prefix}_first"
                key_all = f"{prefix}_all"
                if median_ms is not None:
                    timings_ms[key_first] = float(median_ms)
                    timings_ms[key_all] = float(median_ms)
                    timings_ms_stdev[key_first] = float(stdev_ms)
                    timings_ms_stdev[key_all] = float(stdev_ms)
                if median_kb is not None:
                    memory_kb[key_first] = int(round(median_kb))
                    memory_kb[key_all] = int(round(median_kb))
                    memory_kb_stdev[key_first] = int(round(stdev_kb))
                    memory_kb_stdev[key_all] = int(round(stdev_kb))
                variant_metadata.append(
                    {
                        "variant_id": row.variant_id,
                        "family": row.family,
                        "role": row.role,
                        "label": row.label,
                        "llm_key": row.llm_key,
                        "llm_label": row.llm_label,
                        "timing_keys": {"first": key_first, "all": key_all},
                        "memory_keys": {"first": key_first, "all": key_all},
                    }
                )

        baseline_outputs = per_solver_outputs[baseline_row.variant_id]
        for row in by_role:
            if row.role == "baseline":
                continue
            if selected_family == "dijkstra":
                total = 0
                matches = 0
                for i, out in enumerate(per_solver_outputs[row.variant_id]):
                    if i >= len(baseline_outputs):
                        continue
                    left = normalize_dijkstra_output(baseline_outputs[i])
                    right = normalize_dijkstra_output(out)
                    if not left and not right:
                        continue
                    total += 1
                    if left == right:
                        matches += 1
                mismatches = max(0, total - matches)
            else:
                total = 0
                matches = 0
                for i, out in enumerate(per_solver_outputs[row.variant_id]):
                    if i >= len(baseline_outputs):
                        continue
                    left = parse_solution_count(baseline_outputs[i])
                    right = parse_solution_count(out)
                    if left is None or right is None:
                        continue
                    total += 1
                    if left == right:
                        matches += 1
                mismatches = max(0, total - matches)
            key = row.llm_key or row.variant_id
            if algorithm_input == "subgraph":
                key = row.variant_id
            match_counts[key] = {"matches": matches, "total": total, "mismatches": mismatches}

        output_lines.append(f"[{algorithm_input.upper()} Dynamic Runner]")
        output_lines.append(f"Family: {selected_family}")
        output_lines.append(f"Iterations: {iterations}")
        output_lines.append(f"Warmup: {warmup}")
        output_lines.append(f"Seed used: {base_seed}")
        if skipped_rows:
            output_lines.append(f"Skipped optional variants: {len(skipped_rows)}")
            for item in skipped_rows:
                output_lines.append(f"  - {item}")
        output_lines.append("")
        for row in by_role:
            key = build_variant_metric_key(row)
            if algorithm_input == "dijkstra":
                metric_key = key
                ms = timings_ms.get(metric_key)
                kb = memory_kb.get(metric_key)
                ms_stdev = timings_ms_stdev.get(metric_key)
                kb_stdev = memory_kb_stdev.get(metric_key)
            else:
                metric_prefix = key
                if algorithm_input == "subgraph":
                    metric_prefix = f"{selected_family}_{metric_prefix}"
                ms = timings_ms.get(f"{metric_prefix}_all")
                kb = memory_kb.get(f"{metric_prefix}_all")
                ms_stdev = timings_ms_stdev.get(f"{metric_prefix}_all")
                kb_stdev = memory_kb_stdev.get(f"{metric_prefix}_all")
            output_lines.append(f"[{row.label}] runtime_ms={ms if ms is not None else 'n/a'} peak_rss_kb={kb if kb is not None else 'n/a'}")
            output_lines.append(f"{row.label} stats:")
            output_lines.append(
                f"  runtime_median_ms={ms if ms is not None else 'n/a'} "
                f"runtime_stdev_ms={ms_stdev if ms_stdev is not None else 'n/a'}"
            )
            output_lines.append(
                f"  peak_rss_median_kb={kb if kb is not None else 'n/a'} "
                f"peak_rss_stdev_kb={kb_stdev if kb_stdev is not None else 'n/a'}"
            )
            output_lines.append(f"  samples={len(per_solver_times.get(row.variant_id, []))}")
            if row.role != "baseline":
                match_key = row.llm_key or row.variant_id
                if algorithm_input == "subgraph":
                    match_key = row.variant_id
                match_row = match_counts.get(match_key)
                if isinstance(match_row, dict):
                    output_lines.append(
                        "  equivalence: "
                        f"matches={match_row.get('matches', 'n/a')} "
                        f"total={match_row.get('total', 'n/a')} "
                        f"mismatches={match_row.get('mismatches', 'n/a')}"
                    )
            output_lines.append("")

    except Exception as exc:
        exit_code = 1
        output_lines.append(str(exc))

    run_duration_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    RESULT_TEXT_PATH.write_text("\n".join(output_lines).strip() + "\n", encoding="utf-8")

    metrics = {
        "ALGORITHM_INPUT": algorithm_input,
        "EXIT_CODE": str(exit_code),
        "REQUEST_ID_INPUT": request_id,
        "INPUT_MODE_INPUT": input_mode,
        "INPUT_FILES_INPUT": str(os.environ.get("INPUT_FILES_INPUT", "") or ""),
        "GENERATOR_N_INPUT": str(n),
        "GENERATOR_K_INPUT": str(k),
        "GENERATOR_DENSITY_INPUT": str(density),
        "SEED_USED": str(base_seed),
        "ITERATIONS": str(iterations),
        "WARMUP": str(warmup),
        "RUN_DURATION_MS": f"{run_duration_ms:.3f}",
        "SUBGRAPH_PHASE": subgraph_phase if algorithm_input == "subgraph" else "",
        "TIMINGS_MS_JSON": json.dumps(timings_ms, separators=(",", ":"), sort_keys=True),
        "TIMINGS_MS_STDEV_JSON": json.dumps(timings_ms_stdev, separators=(",", ":"), sort_keys=True),
        "MEMORY_KB_JSON": json.dumps(memory_kb, separators=(",", ":"), sort_keys=True),
        "MEMORY_KB_STDEV_JSON": json.dumps(memory_kb_stdev, separators=(",", ":"), sort_keys=True),
        "MATCH_COUNTS_JSON": json.dumps(match_counts, separators=(",", ":"), sort_keys=True),
        "VARIANT_METADATA_JSON": json.dumps(variant_metadata, separators=(",", ":"), sort_keys=True),
    }

    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    github_output = str(os.environ.get("GITHUB_OUTPUT", "") or "").strip()
    if github_output:
        path = Path(github_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for key, value in metrics.items():
                handle.write(f"{key}={value}\n")
            handle.write(f"RUN_METRICS_JSON={METRICS_PATH.as_posix()}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
