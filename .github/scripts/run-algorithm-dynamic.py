#!/usr/bin/env python3
"""Dynamic GitHub benchmark runner using discovered solver variants."""

from __future__ import annotations

import json
import math
import os
import random
import re
import shlex
import signal
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
VISUALIZATION_SOLUTION_CAP = 2000
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


def _simpson_integral(func, a: float, b: float) -> float:
    c = (a + b) * 0.5
    h = b - a
    return (h / 6.0) * (func(a) + (4.0 * func(c)) + func(b))


def _adaptive_simpson(func, a: float, b: float, eps: float, whole: float, depth: int) -> float:
    c = (a + b) * 0.5
    left = _simpson_integral(func, a, c)
    right = _simpson_integral(func, c, b)
    delta = left + right - whole
    if depth <= 0 or abs(delta) <= 15.0 * eps:
        return left + right + (delta / 15.0)
    return (
        _adaptive_simpson(func, a, c, eps * 0.5, left, depth - 1)
        + _adaptive_simpson(func, c, b, eps * 0.5, right, depth - 1)
    )


def student_t_two_sided_p_value(t_stat: float, degrees_of_freedom: int) -> float | None:
    if not math.isfinite(t_stat):
        return None
    df = int(degrees_of_freedom)
    if df <= 0:
        return None
    x = abs(float(t_stat))
    if x <= 0.0:
        return 1.0
    if x >= 50.0:
        return 0.0
    if df >= 200:
        tail = 0.5 * math.erfc(x / math.sqrt(2.0))
        return max(0.0, min(1.0, 2.0 * tail))

    log_c = math.lgamma((df + 1.0) * 0.5) - math.lgamma(df * 0.5) - 0.5 * math.log(df * math.pi)
    c = math.exp(log_c)

    def pdf(val: float) -> float:
        return c * ((1.0 + ((val * val) / float(df))) ** (-(df + 1.0) * 0.5))

    whole = _simpson_integral(pdf, 0.0, x)
    area_0_to_x = _adaptive_simpson(pdf, 0.0, x, 1e-8, whole, depth=20)
    cdf = max(0.0, min(1.0, 0.5 + area_0_to_x))
    return max(0.0, min(1.0, 2.0 * (1.0 - cdf)))


def student_t_critical_two_sided(alpha: float, degrees_of_freedom: int) -> float | None:
    df = int(degrees_of_freedom)
    if df <= 0:
        return None
    target = float(alpha)
    if not math.isfinite(target) or target <= 0.0 or target >= 1.0:
        return None
    lo = 0.0
    hi = 1.0
    p_hi = student_t_two_sided_p_value(hi, df)
    guard = 0
    while (p_hi is None or p_hi > target) and hi < 1_000_000.0:
        lo = hi
        hi *= 2.0
        p_hi = student_t_two_sided_p_value(hi, df)
        guard += 1
        if guard > 80:
            break
    if p_hi is None:
        return None
    for _ in range(64):
        mid = (lo + hi) * 0.5
        p_mid = student_t_two_sided_p_value(mid, df)
        if p_mid is None:
            return None
        if p_mid > target:
            lo = mid
        else:
            hi = mid
    return hi


def normal_two_sided_p_value_from_z(z_score: float) -> float | None:
    if not math.isfinite(z_score):
        return None
    tail = 0.5 * math.erfc(abs(float(z_score)) / math.sqrt(2.0))
    return max(0.0, min(1.0, 2.0 * tail))


def cliffs_delta(left: list[float], right: list[float]) -> float | None:
    a = [float(v) for v in left if isinstance(v, (int, float)) and math.isfinite(float(v))]
    b = [float(v) for v in right if isinstance(v, (int, float)) and math.isfinite(float(v))]
    if not a or not b:
        return None
    greater = 0
    less = 0
    for x in a:
        for y in b:
            if x > y:
                greater += 1
            elif x < y:
                less += 1
    denom = len(a) * len(b)
    if denom <= 0:
        return None
    return float(greater - less) / float(denom)


def mann_whitney_u_test(left: list[float], right: list[float]) -> dict:
    x = [float(v) for v in left if isinstance(v, (int, float)) and math.isfinite(float(v))]
    y = [float(v) for v in right if isinstance(v, (int, float)) and math.isfinite(float(v))]
    nx = len(x)
    ny = len(y)
    if nx == 0 or ny == 0:
        return {
            "u_stat": None,
            "u_stat_alt": None,
            "z_score": None,
            "p_value_two_sided": None,
        }

    combined = [(val, 0) for val in x] + [(val, 1) for val in y]
    combined.sort(key=lambda item: item[0])
    rank_sum_x = 0.0
    tie_sizes: list[int] = []
    idx = 0
    while idx < len(combined):
        j = idx + 1
        while j < len(combined) and combined[j][0] == combined[idx][0]:
            j += 1
        avg_rank = (float(idx + 1) + float(j)) * 0.5
        block = combined[idx:j]
        tie_sizes.append(len(block))
        rank_sum_x += avg_rank * float(sum(1 for _value, grp in block if grp == 0))
        idx = j

    u_x = rank_sum_x - (float(nx) * float(nx + 1) * 0.5)
    u_y = float(nx * ny) - u_x
    u_stat = min(u_x, u_y)
    mean_u = float(nx * ny) * 0.5

    n_total = nx + ny
    tie_term = sum(float(t * t * t - t) for t in tie_sizes)
    denom = float(n_total * n_total * n_total - n_total)
    tie_correction = 1.0 - (tie_term / denom) if denom > 0.0 else 1.0
    sigma_sq = float(nx * ny * (n_total + 1)) / 12.0
    sigma_sq *= max(0.0, tie_correction)

    if sigma_sq <= 0.0:
        if abs(u_stat - mean_u) <= 1e-12:
            z_score = 0.0
            p_value = 1.0
        else:
            z_score = math.copysign(float("inf"), u_stat - mean_u)
            p_value = 0.0
    else:
        sigma = math.sqrt(sigma_sq)
        z_score = (u_stat - mean_u) / sigma
        p_value = normal_two_sided_p_value_from_z(z_score)

    return {
        "u_stat": float(u_stat),
        "u_stat_alt": float(max(u_x, u_y)),
        "z_score": None if z_score is None else float(z_score),
        "p_value_two_sided": None if p_value is None else float(p_value),
    }


def summarize_runtime_comparison(
    *,
    variant_samples_ms: list[float],
    baseline_samples_ms: list[float],
    alpha: float = 0.05,
) -> dict:
    variant = [float(v) for v in variant_samples_ms if isinstance(v, (int, float)) and math.isfinite(float(v))]
    baseline = [float(v) for v in baseline_samples_ms if isinstance(v, (int, float)) and math.isfinite(float(v))]
    pair_count = min(len(variant), len(baseline))
    if pair_count <= 0:
        return {
            "n": 0,
            "mean_delta_ms": None,
            "median_delta_ms": None,
            "stdev_delta_ms": None,
            "delta_ci_95_ms": {"low": None, "high": None},
            "paired_t_test": {"t_stat": None, "degrees_of_freedom": 0, "p_value_two_sided": None},
            "mann_whitney_u": mann_whitney_u_test(variant, baseline),
            "effect_sizes": {
                "cohen_d": None,
                "hedges_g": None,
                "cliffs_delta": cliffs_delta(variant, baseline),
            },
            "direction": "insufficient_data",
            "significant_at_alpha": None,
            "alpha": float(alpha),
        }

    deltas = [variant[i] - baseline[i] for i in range(pair_count)]
    mean_delta = float(statistics.mean(deltas))
    median_delta = float(statistics.median(deltas))
    if pair_count >= 2:
        sd_delta = float(statistics.stdev(deltas))
    else:
        sd_delta = 0.0

    if pair_count < 2:
        t_stat = None
        p_value = None
        ci_low = None
        ci_high = None
    elif sd_delta <= 0.0:
        if abs(mean_delta) <= 1e-12:
            t_stat = 0.0
            p_value = 1.0
        else:
            t_stat = math.copysign(float("inf"), mean_delta)
            p_value = 0.0
        ci_low = mean_delta
        ci_high = mean_delta
    else:
        se = sd_delta / math.sqrt(float(pair_count))
        t_stat = mean_delta / se
        p_value = student_t_two_sided_p_value(t_stat, pair_count - 1)
        t_crit = student_t_critical_two_sided(alpha, pair_count - 1)
        if t_crit is None:
            ci_low = None
            ci_high = None
        else:
            half = float(t_crit) * se
            ci_low = mean_delta - half
            ci_high = mean_delta + half

    if pair_count < 2:
        cohen_d = None
    elif sd_delta <= 0.0:
        cohen_d = 0.0 if abs(mean_delta) <= 1e-12 else math.copysign(float("inf"), mean_delta)
    else:
        cohen_d = mean_delta / sd_delta
    if cohen_d is None:
        hedges_g = None
    else:
        correction = 1.0 if pair_count <= 2 else (1.0 - (3.0 / ((4.0 * float(pair_count)) - 5.0)))
        hedges_g = float(cohen_d) * correction

    if abs(mean_delta) <= 1e-12:
        direction = "equal"
    elif mean_delta > 0.0:
        direction = "slower"
    else:
        direction = "faster"

    return {
        "n": int(pair_count),
        "mean_delta_ms": float(mean_delta),
        "median_delta_ms": float(median_delta),
        "stdev_delta_ms": float(sd_delta),
        "delta_ci_95_ms": {
            "low": None if ci_low is None else float(ci_low),
            "high": None if ci_high is None else float(ci_high),
        },
        "paired_t_test": {
            "t_stat": None if t_stat is None else float(t_stat),
            "degrees_of_freedom": int(max(0, pair_count - 1)),
            "p_value_two_sided": None if p_value is None else float(p_value),
        },
        "mann_whitney_u": mann_whitney_u_test(variant, baseline),
        "effect_sizes": {
            "cohen_d": None if cohen_d is None else float(cohen_d),
            "hedges_g": None if hedges_g is None else float(hedges_g),
            "cliffs_delta": cliffs_delta(variant, baseline),
        },
        "direction": direction,
        "significant_at_alpha": None if p_value is None else bool(p_value < float(alpha)),
        "alpha": float(alpha),
    }


def build_runtime_statistical_tests(
    *,
    by_role: list["SolverRow"],
    baseline_row: "SolverRow",
    selected_family: str,
    per_solver_times: dict[tuple[str, str], list[float]],
    alpha: float = 0.05,
) -> dict:
    mode_order = ["single"] if selected_family in {"dijkstra", "sp_via"} else ["first", "all"]
    rows: list[dict] = []
    for row in by_role:
        if row.role == "baseline":
            continue
        for mode in mode_order:
            baseline_samples = list(per_solver_times.get((baseline_row.variant_id, mode), []))
            variant_samples = list(per_solver_times.get((row.variant_id, mode), []))
            summary = summarize_runtime_comparison(
                variant_samples_ms=variant_samples,
                baseline_samples_ms=baseline_samples,
                alpha=alpha,
            )
            rows.append(
                {
                    "variant_id": row.variant_id,
                    "variant_label": row.label,
                    "baseline_variant_id": baseline_row.variant_id,
                    "baseline_label": baseline_row.label,
                    "mode": mode,
                    **summary,
                }
            )
    return {
        "metric": "runtime_ms",
        "alpha": float(alpha),
        "pairs": rows,
        "notes": [
            "paired_t_test uses matched iteration deltas (variant - baseline).",
            "mann_whitney_u compares the two runtime distributions.",
            "cohen_d and hedges_g are standardized effect sizes on paired deltas.",
            "cliffs_delta is the probability dominance effect size.",
        ],
    }


def parse_solution_count(text: str) -> int | None:
    src = str(text or "").strip()
    if not src:
        return None
    patterns = [
        r"(?im)\bsolution[_\s-]*count\s*[:=]\s*(-?\d+)\b",
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

    # VF3-style compact output: "<solutions> <first_time> <all_time>"
    compact_three = re.compile(
        r"^\s*(-?\d+)\s+[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
        r"(?:\s+[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?){1,}\s*$"
    )
    for line in lines:
        m = compact_three.match(line)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass

    # Fallback: count mapping lines when explicit count is not present.
    mapping_lines = 0
    for line in lines:
        if re.search(r"(?i)\bmapping\s*[:=]", line) and re.search(r"\d+\s*->\s*\d+", line):
            mapping_lines += 1
    if mapping_lines > 0:
        return mapping_lines

    pair_lines = 0
    for line in lines:
        if re.search(r"\(\s*\d+\s*->\s*\d+\s*\)", line):
            pair_lines += 1
    if pair_lines > 0:
        return pair_lines

    # Last-resort numeric line (skip obvious timing/resource lines).
    noise_words = ("runtime", "time", "ms", "rss", "memory", "peak", "loaded", "finished")
    for line in lines:
        low = line.lower()
        if any(word in low for word in noise_words):
            continue
        m = re.match(r"^\s*(-?\d+)\b", line)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def parse_solution_count_sections(output_text: str) -> dict[str, list[str]]:
    lines = [str(line or "").strip() for line in str(output_text or "").replace("\r", "").split("\n")]
    sections: dict[str, list[str]] = {}
    current = ""
    i = 0
    while i < len(lines):
        trimmed = lines[i]
        if not trimmed:
            i += 1
            continue
        section_match = re.match(r"^\[([^\]]+)\](?:\s*(.*))?$", trimmed)
        if section_match:
            section_name = str(section_match.group(1) or "").strip()
            suffix = str(section_match.group(2) or "").strip()
            current = f"{section_name} {suffix}".strip() if suffix else section_name
            i += 1
            continue
        if re.match(r"^Solution counts:\s*", trimmed, flags=re.IGNORECASE):
            block = re.sub(r"^Solution counts:\s*", "", trimmed, flags=re.IGNORECASE).strip()
            while "]" not in block and (i + 1) < len(lines):
                next_line = str(lines[i + 1] or "").strip()
                if next_line and re.match(r"^\[.+\]$", next_line):
                    break
                i += 1
                if next_line:
                    block += (" " if block else "") + next_line
                if "]" in next_line:
                    break
            open_idx = block.find("[")
            close_idx = block.rfind("]")
            if open_idx >= 0 and close_idx > open_idx:
                inner = block[open_idx + 1 : close_idx]
                counts = [item.strip() for item in inner.split(",") if item.strip()]
                if counts:
                    sections[current or "unknown"] = counts
        i += 1
    return sections


def parse_count_token(value: str) -> int | None:
    token = str(value or "").strip()
    if not token or token.upper() == "NA":
        return None
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    m = re.search(r"-?\d+", token)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def load_previous_vf3_baseline_counts(iterations: int) -> list[int | None] | None:
    result_path = OUTPUTS_DIR / "result.json"
    if not result_path.is_file():
        return None
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    output_text = str(payload.get("output") or "")
    if not output_text:
        return None
    sections = parse_solution_count_sections(output_text)
    if not sections:
        return None

    selected: list[str] | None = None
    for section, counts in sections.items():
        key = section.strip().lower()
        if "vf3 baseline" in key or "subgraph vf3 baseline" in key:
            selected = counts
            break
    if not selected:
        return None

    parsed = [parse_count_token(item) for item in selected]
    if len(parsed) < iterations:
        parsed.extend([None] * (iterations - len(parsed)))
    return parsed[:iterations]


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


def format_return_code(rc: int) -> str:
    if rc >= 0:
        return str(rc)
    signum = -rc
    try:
        sig_name = signal.Signals(signum).name
    except Exception:
        sig_name = f"SIG{signum}"
    return f"{rc} ({sig_name})"


def truncate_text(value: str, max_chars: int = 1200) -> str:
    text = str(value or "").replace("\r", "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]..."


def build_process_error(prefix: str, row: SolverRow, command: list[str], rc: int, stdout: str, stderr: str) -> str:
    lines: list[str] = []
    lines.append(f"{prefix} for {row.variant_id}: code={format_return_code(rc)}")
    if rc == -4:
        lines.append(
            "Hint: SIGILL often means unsupported CPU instructions in the binary "
            "(for example binaries built with -march=native on a different machine)."
        )
    lines.append(f"command: {' '.join(shlex.quote(part) for part in command)}")
    stderr_text = str(stderr or "").strip()
    stdout_text = str(stdout or "").strip()
    if stderr_text:
        lines.append("stderr:")
        lines.append(truncate_text(stderr_text))
    elif stdout_text:
        lines.append("stdout:")
        lines.append(truncate_text(stdout_text))
    else:
        lines.append("stderr/stdout were empty.")
    return "\n".join(lines)


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
        if not variant_id or family not in {"dijkstra", "sp_via", "vf3", "glasgow"}:
            continue
        if not binary_path:
            if role == "baseline":
                if family == "dijkstra":
                    binary_path = "baselines/dijkstra"
                elif family == "sp_via":
                    binary_path = "baselines/via_dijkstra"
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
    if algorithm in {"dijkstra", "sp_via"}:
        cmd = [
            sys.executable,
            "utilities/generate_graphs.py",
            "--algorithm",
            algorithm,
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
            raise RuntimeError("Generator did not return shortest-path input path")
        graph_path = Path(paths[0]).resolve()
        return {"seed": Path(str(seed)), "dijkstra": graph_path, "sp_via": graph_path}

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
    if algorithm in {"dijkstra", "sp_via"}:
        if len(files) < 1:
            raise RuntimeError(f"{algorithm} requires one input file")
        return {"seed": Path(""), "dijkstra": files[0], "sp_via": files[0]}
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


def resolve_row_binary(row: SolverRow) -> Path:
    binary_path = Path(row.binary_path)
    if binary_path.is_absolute():
        return binary_path
    return resolve_binary(row.binary_path)


def make_mode_commands(row: SolverRow, inputs: dict[str, Path], via_label: str) -> dict[str, list[str]]:
    binary = resolve_row_binary(row)
    if row.family == "dijkstra":
        return {
            "single": [str(binary), str(inputs["dijkstra"])],
        }
    if row.family == "sp_via":
        command = [str(binary), str(inputs.get("sp_via", inputs["dijkstra"]))]
        if via_label:
            command.append(via_label)
        return {
            "single": command,
        }
    if row.family == "vf3":
        if row.role == "baseline":
            return {
                "first": [str(binary), "-u", "-r", "0", "-F", "-e", str(inputs["vf_pattern"]), str(inputs["vf_target"])],
                "all": [str(binary), "-u", "-r", "0", "-e", str(inputs["vf_pattern"]), str(inputs["vf_target"])],
            }
        return {
            "first": [str(binary), str(inputs["vf_pattern"]), str(inputs["vf_target"])],
            "all": [str(binary), str(inputs["vf_pattern"]), str(inputs["vf_target"])],
        }
    if row.family == "glasgow":
        if row.role == "baseline":
            return {
                "first": [str(binary), "--format", "vertexlabelledlad", str(inputs["lad_pattern"]), str(inputs["lad_target"])],
                "all": [str(binary), "--count-solutions", "--format", "vertexlabelledlad", str(inputs["lad_pattern"]), str(inputs["lad_target"])],
            }
        base = [str(binary), str(inputs["lad_pattern"]), str(inputs["lad_target"])]
        return {
            "first": [*base, "--print-mappings"],
            "all": list(base),
        }
    raise RuntimeError(f"Unsupported family: {row.family}")


def parse_int_tokens(line: str) -> list[int]:
    return [int(item) for item in re.findall(r"-?\d+", str(line or ""))]


def parse_vf_graph(path: Path) -> list[list[int]]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise RuntimeError(f"Empty VF graph file: {path}")
    n_tokens = parse_int_tokens(lines[0])
    if not n_tokens:
        raise RuntimeError(f"Invalid VF header in {path}")
    n = max(0, int(n_tokens[0]))
    adj: list[set[int]] = [set() for _ in range(n)]
    idx = 1
    for _ in range(n):
        if idx >= len(lines):
            break
        idx += 1
    for u in range(n):
        if idx >= len(lines):
            break
        count_tokens = parse_int_tokens(lines[idx])
        idx += 1
        edge_count = int(count_tokens[0]) if count_tokens else 0
        for _ in range(max(0, edge_count)):
            if idx >= len(lines):
                break
            edge_tokens = parse_int_tokens(lines[idx])
            idx += 1
            if not edge_tokens:
                continue
            if len(edge_tokens) >= 2:
                v = int(edge_tokens[1])
            else:
                v = int(edge_tokens[0])
            if 0 <= v < n and v != u:
                adj[u].add(v)
    return [sorted(row) for row in adj]


def parse_lad_graph(path: Path) -> list[list[int]]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise RuntimeError(f"Empty LAD graph file: {path}")
    n_tokens = parse_int_tokens(lines[0])
    if not n_tokens:
        raise RuntimeError(f"Invalid LAD header in {path}")
    n = max(0, int(n_tokens[0]))
    adj: list[set[int]] = [set() for _ in range(n)]
    for u in range(n):
        if u + 1 >= len(lines):
            break
        values = parse_int_tokens(lines[u + 1])
        if not values:
            continue
        neighbors: list[int]
        unlabeled_match = len(values) >= 1 and values[0] >= 0 and len(values) == 1 + int(values[0])
        labeled_match = len(values) >= 2 and values[1] >= 0 and len(values) == 2 + int(values[1])
        if labeled_match and not unlabeled_match:
            degree = int(values[1])
            neighbors = values[2 : 2 + degree]
        elif unlabeled_match:
            degree = int(values[0])
            neighbors = values[1 : 1 + degree]
        elif len(values) >= 2:
            degree = int(values[1])
            neighbors = values[2 : 2 + max(0, degree)]
        else:
            degree = int(values[0])
            neighbors = values[1 : 1 + max(0, degree)]
        for v in neighbors:
            if 0 <= v < n and v != u:
                adj[u].add(v)
    return [sorted(row) for row in adj]


def edge_key(u: int, v: int) -> tuple[int, int] | None:
    if not isinstance(u, int) or not isinstance(v, int):
        return None
    if u == v:
        return None
    return (u, v) if u < v else (v, u)


def parse_pattern_nodes_hint(inputs: dict[str, Path], selected_family: str) -> list[int] | None:
    try:
        if selected_family == "vf3":
            pattern_path = Path(inputs["vf_pattern"])
        else:
            pattern_path = Path(inputs["lad_pattern"])
    except Exception:
        return None
    metadata_path = pattern_path.parent / "metadata.json"
    if not metadata_path.is_file():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    values = payload.get("pattern_nodes")
    if not isinstance(values, list) or not values:
        return None
    parsed: list[int] = []
    for raw in values:
        try:
            parsed.append(int(raw))
        except (TypeError, ValueError):
            return None
    return parsed


def mapping_from_pattern_nodes_hint(
    hint_nodes: list[int] | None,
    pattern_n: int,
    target_n: int,
    pattern_edges: list[tuple[int, int]],
    target_edge_set: set[tuple[int, int]],
) -> dict[int, int] | None:
    if not hint_nodes or pattern_n <= 0:
        return None
    if len(hint_nodes) < pattern_n:
        return None
    mapping: dict[int, int] = {}
    used: set[int] = set()
    for p in range(pattern_n):
        t = int(hint_nodes[p])
        if t < 0 or t >= target_n or t in used:
            return None
        used.add(t)
        mapping[p] = t
    for a, b in pattern_edges:
        ta = mapping.get(a)
        tb = mapping.get(b)
        if ta is None or tb is None:
            return None
        ek = edge_key(ta, tb)
        if ek is None or ek not in target_edge_set:
            return None
    return mapping


def extract_mappings_from_text(text: str, limit: int = VISUALIZATION_SOLUTION_CAP) -> list[dict[int, int]]:
    src = str(text or "")
    if not src:
        return []
    out: list[dict[int, int]] = []
    seen: set[str] = set()
    max_items = max(1, int(limit))

    def add_pairs(pairs: list[tuple[str, str]]) -> None:
        if not pairs:
            return
        mapping: dict[int, int] = {}
        for p_raw, t_raw in pairs:
            try:
                p = int(p_raw)
                t = int(t_raw)
            except ValueError:
                continue
            mapping[p] = t
        if not mapping:
            return
        key = json.dumps(mapping, sort_keys=True)
        if key in seen:
            return
        seen.add(key)
        out.append(mapping)

    for raw_line in src.replace("\r", "").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        pairs1 = [(m.group(1), m.group(2)) for m in re.finditer(r"\(\s*(\d+)\s*->\s*(\d+)\s*\)", line)]
        if pairs1:
            add_pairs(pairs1)
            if len(out) >= max_items:
                break
            continue
        pairs2 = [(m.group(1), m.group(2)) for m in re.finditer(r"(\d+)\s*,\s*(\d+)\s*:", line)]
        if pairs2:
            add_pairs(pairs2)
            if len(out) >= max_items:
                break
            continue
        if re.search(r"mapping\s*[:=]", line, flags=re.IGNORECASE) or "->" in line:
            pairs3 = [(m.group(1), m.group(2)) for m in re.finditer(r"(\d+)\s*->\s*(\d+)", line)]
            if pairs3:
                add_pairs(pairs3)
                if len(out) >= max_items:
                    break
                continue
            pairs4 = [(m.group(1), m.group(2)) for m in re.finditer(r"(\d+)\s*=\s*(\d+)", line)]
            if pairs4:
                add_pairs(pairs4)
                if len(out) >= max_items:
                    break
                continue

    if not out:
        pairs = [(m.group(1), m.group(2)) for m in re.finditer(r"\(\s*(\d+)\s*->\s*(\d+)\s*\)", src)]
        if not pairs:
            pairs = [(m.group(1), m.group(2)) for m in re.finditer(r"(\d+)\s*->\s*(\d+)", src)]
        if pairs:
            add_pairs(pairs)

    return out[:max_items]


def normalize_mappings(
    mappings: list[dict[int, int]],
    pattern_n: int,
    target_n: int,
    limit: int = VISUALIZATION_SOLUTION_CAP,
) -> list[dict[int, int]]:
    out: list[dict[int, int]] = []
    seen: set[str] = set()
    max_items = max(1, int(limit))
    for item in mappings:
        if not isinstance(item, dict):
            continue
        pairs: list[tuple[int, int]] = []
        for p_raw, t_raw in item.items():
            try:
                p = int(p_raw)
                t = int(t_raw)
            except (TypeError, ValueError):
                continue
            pairs.append((p, t))
        if not pairs:
            continue

        allow_p_shift = pattern_n > 0 and all(1 <= p <= pattern_n for p, _ in pairs)
        allow_t_shift = target_n > 0 and all(1 <= t <= target_n for _, t in pairs)
        variants = [(0, 0)]
        if allow_p_shift:
            variants.append((-1, 0))
        if allow_t_shift:
            variants.append((0, -1))
        if allow_p_shift and allow_t_shift:
            variants.append((-1, -1))

        best_map: dict[int, int] | None = None
        best_score = -1
        best_penalty = 10**9
        for p_shift, t_shift in variants:
            candidate: dict[int, int] = {}
            for p0, t0 in pairs:
                p = p0 + p_shift
                t = t0 + t_shift
                if p < 0 or p >= pattern_n or t < 0 or t >= target_n:
                    continue
                candidate[p] = t
            score = len(candidate)
            penalty = abs(p_shift) + abs(t_shift)
            if score > best_score or (score == best_score and penalty < best_penalty):
                best_map = candidate
                best_score = score
                best_penalty = penalty

        if not best_map:
            continue
        key = json.dumps(best_map, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(best_map)
        if len(out) >= max_items:
            break
    return out


def undirected_edge_set(adj: list[list[int]]) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for u, neighbors in enumerate(adj):
        for v in neighbors:
            ek = edge_key(u, v)
            if ek is not None:
                edges.add(ek)
    return edges


def is_valid_subgraph_witness_mapping(
    pattern_adj: list[list[int]],
    target_adj: list[list[int]],
    mapping: dict[int, int],
) -> bool:
    pattern_n = len(pattern_adj)
    target_n = len(target_adj)
    if pattern_n <= 0 or target_n <= 0:
        return False
    if len(mapping) < pattern_n:
        return False

    normalized: dict[int, int] = {}
    used_targets: set[int] = set()
    for p in range(pattern_n):
        raw_t = mapping.get(p)
        if raw_t is None:
            return False
        try:
            t = int(raw_t)
        except (TypeError, ValueError):
            return False
        if t < 0 or t >= target_n:
            return False
        if t in used_targets:
            return False
        used_targets.add(t)
        normalized[p] = t

    target_edges = undirected_edge_set(target_adj)
    for u, neighbors in enumerate(pattern_adj):
        for v in neighbors:
            ek_pattern = edge_key(u, v)
            if ek_pattern is None:
                continue
            tu = normalized.get(u)
            tv = normalized.get(v)
            if tu is None or tv is None:
                return False
            ek_target = edge_key(tu, tv)
            if ek_target is None or ek_target not in target_edges:
                return False
    return True


def evaluate_witness_mapping_output(
    output_text: str,
    *,
    pattern_adj: list[list[int]],
    target_adj: list[list[int]],
    limit: int = 64,
) -> tuple[bool, int, int]:
    parsed = extract_mappings_from_text(output_text, limit=limit)
    normalized = normalize_mappings(parsed, len(pattern_adj), len(target_adj), limit=limit)
    valid = 0
    for mapping in normalized:
        if is_valid_subgraph_witness_mapping(pattern_adj, target_adj, mapping):
            valid += 1
    return (valid > 0), len(normalized), valid


def find_subgraph_mappings(
    pattern_adj: list[list[int]],
    target_adj: list[list[int]],
    *,
    limit: int = 64,
    time_budget_ms: int = 800,
) -> list[dict[int, int]]:
    p_n = len(pattern_adj)
    t_n = len(target_adj)
    if p_n == 0 or t_n == 0 or p_n > t_n:
        return []

    p_sets = [set(int(v) for v in row if isinstance(v, int)) for row in pattern_adj]
    t_sets = [set(int(v) for v in row if isinstance(v, int)) for row in target_adj]
    p_deg = [len(s) for s in p_sets]
    t_deg = [len(s) for s in t_sets]

    candidates: list[list[int]] = []
    for p in range(p_n):
        cand = [t for t in range(t_n) if t_deg[t] >= p_deg[p]]
        if not cand:
            return []
        candidates.append(cand)

    order = list(range(p_n))
    order.sort(key=lambda p: (len(candidates[p]), -p_deg[p]))
    mapping = [-1] * p_n
    used = [False] * t_n
    results: list[dict[int, int]] = []
    started = time.perf_counter()
    budget_sec = max(0.05, float(time_budget_ms) / 1000.0)

    def timed_out() -> bool:
        return (time.perf_counter() - started) > budget_sec

    def consistent(p: int, t: int) -> bool:
        for q in range(p_n):
            tq = mapping[q]
            if tq < 0:
                continue
            if q in p_sets[p] and tq not in t_sets[t]:
                return False
        return True

    def search(depth: int) -> bool:
        if timed_out():
            return False
        if len(results) >= max(1, int(limit)):
            return True
        if depth >= p_n:
            results.append({i: mapping[i] for i in range(p_n)})
            return len(results) >= max(1, int(limit))

        p = order[depth]
        cand = sorted(candidates[p], key=lambda t: len(t_sets[t]))
        for t in cand:
            if used[t]:
                continue
            if not consistent(p, t):
                continue
            used[t] = True
            mapping[p] = t
            stop = search(depth + 1)
            mapping[p] = -1
            used[t] = False
            if stop:
                return True
            if timed_out():
                return False
        return False

    search(0)
    return results


def render_ascii_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not headers:
        return []
    cols = len(headers)
    normalized_rows = []
    for row in rows:
        r = [str(cell) for cell in (row or [])]
        if len(r) < cols:
            r.extend([""] * (cols - len(r)))
        normalized_rows.append(r[:cols])
    widths = [len(str(h)) for h in headers]
    for row in normalized_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(values: list[str]) -> str:
        return " | ".join(str(values[i]).ljust(widths[i]) for i in range(cols))

    sep = "-+-".join("-" * widths[i] for i in range(cols))
    lines = [fmt_row([str(h) for h in headers]), sep]
    for row in normalized_rows:
        lines.append(fmt_row(row))
    return lines


def fmt_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.3f}"


def fmt_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(int(value))


def fmt_median_stdev(median_value: float | int | None, stdev_value: float | int | None) -> str:
    med = "n/a" if median_value is None else f"{float(median_value):.3f}"
    sd = "n/a" if stdev_value is None else f"{float(stdev_value):.3f}"
    return f"median={med} stdev={sd}"


def fmt_labeled_median_stdev(
    label: str,
    median_value: float | int | None,
    stdev_value: float | int | None,
    *,
    label_width: int = 24,
    value_width: int = 10,
) -> str:
    med = "n/a" if median_value is None else f"{float(median_value):.3f}"
    sd = "n/a" if stdev_value is None else f"{float(stdev_value):.3f}"
    return (
        f"{str(label):<{label_width}} "
        f"median={med:>{value_width}}  "
        f"stdev={sd:>{value_width}}"
    )


def fmt_labeled_value(label: str, value: str, *, label_width: int = 24) -> str:
    return f"{str(label):<{label_width}} {str(value)}"


def build_visualization_iteration(
    *,
    algorithm: str,
    pattern_adj: list[list[int]],
    target_adj: list[list[int]],
    mapping_sources: list[str],
    pattern_nodes_hint: list[int] | None,
    iteration: int,
    seed: int | None,
) -> dict:
    pattern_n = len(pattern_adj)
    target_n = len(target_adj)

    target_edge_set: set[tuple[int, int]] = set()
    for u, neighbors in enumerate(target_adj):
        for v in neighbors:
            key = edge_key(u, v)
            if key is not None:
                target_edge_set.add(key)

    pattern_edges: list[tuple[int, int]] = []
    pattern_edge_set: set[tuple[int, int]] = set()
    for u, neighbors in enumerate(pattern_adj):
        for v in neighbors:
            key = edge_key(u, v)
            if key is None or key in pattern_edge_set:
                continue
            pattern_edge_set.add(key)
            pattern_edges.append(key)
    pattern_edges.sort()

    max_nodes = 4000
    max_edges = 4000
    allowed_nodes = set(range(min(target_n, max_nodes)))
    sorted_target_edges = sorted(target_edge_set)
    truncated = target_n > max_nodes or len(sorted_target_edges) > max_edges
    limited_edges = sorted_target_edges[:max_edges]
    limited_edge_set = set(limited_edges)

    nodes = [{"data": {"id": str(i), "label": str(i)}} for i in range(min(target_n, max_nodes))]
    edges = [{"data": {"id": f"{a}-{b}", "source": str(a), "target": str(b)}} for a, b in limited_edges]

    expected_solution_count: int | None = None
    parsed_mappings: list[dict[int, int]] = []
    for source in mapping_sources:
        c = parse_solution_count(source)
        if c is not None and c >= 0:
            expected_solution_count = c if expected_solution_count is None else max(expected_solution_count, c)
        parsed_mappings.extend(extract_mappings_from_text(source, limit=VISUALIZATION_SOLUTION_CAP))
        if len(parsed_mappings) >= VISUALIZATION_SOLUTION_CAP:
            break
    normalized = normalize_mappings(
        parsed_mappings,
        pattern_n,
        target_n,
        limit=VISUALIZATION_SOLUTION_CAP,
    )
    if not normalized:
        hinted = mapping_from_pattern_nodes_hint(
            pattern_nodes_hint,
            pattern_n,
            target_n,
            pattern_edges,
            target_edge_set,
        )
        if hinted:
            normalized = normalize_mappings(
                [hinted],
                pattern_n,
                target_n,
                limit=VISUALIZATION_SOLUTION_CAP,
            )
    # If outputs did not carry full mappings, discover additional mappings for visualization.
    needed = VISUALIZATION_SOLUTION_CAP
    if expected_solution_count is not None and expected_solution_count > 0:
        needed = min(VISUALIZATION_SOLUTION_CAP, int(expected_solution_count))
    if len(normalized) < needed:
        discovered = find_subgraph_mappings(
            pattern_adj,
            target_adj,
            limit=needed,
            time_budget_ms=5000,
        )
        normalized = normalize_mappings(
            list(normalized) + list(discovered),
            pattern_n,
            target_n,
            limit=VISUALIZATION_SOLUTION_CAP,
        )

    solutions = []
    for mapping in normalized:
        mapping_arr: list[int | None] = [None] * pattern_n
        for p, t in mapping.items():
            if 0 <= p < pattern_n and 0 <= t < target_n:
                mapping_arr[p] = t
        highlight_nodes = [str(t) for t in mapping_arr if isinstance(t, int) and t in allowed_nodes]
        highlight_edges: list[str] = []
        for a, b in pattern_edges:
            ta = mapping_arr[a]
            tb = mapping_arr[b]
            if not isinstance(ta, int) or not isinstance(tb, int):
                continue
            ek = edge_key(ta, tb)
            if ek is None:
                continue
            if ek in target_edge_set and ek in limited_edge_set:
                highlight_edges.append(f"{ek[0]}-{ek[1]}")
        solutions.append(
            {
                "mapping": mapping_arr,
                "highlight_nodes": highlight_nodes,
                "highlight_edges": highlight_edges,
            }
        )
        if len(solutions) >= VISUALIZATION_SOLUTION_CAP:
            break

    first = solutions[0] if solutions else None
    cap_reached = len(solutions) >= VISUALIZATION_SOLUTION_CAP
    if expected_solution_count is not None and expected_solution_count > VISUALIZATION_SOLUTION_CAP:
        cap_reached = True
    payload = {
        "algorithm": str(algorithm or "").strip().lower(),
        "seed": seed,
        "iteration": int(iteration),
        "node_count": target_n,
        "edge_count": len(target_edge_set),
        "nodes": nodes,
        "edges": edges,
        "highlight_nodes": (first.get("highlight_nodes") if first else []),
        "highlight_edges": (first.get("highlight_edges") if first else []),
        "pattern_node_count": pattern_n,
        "pattern_nodes": (first.get("mapping") if first else []),
        "pattern_edges": [[a, b] for a, b in pattern_edges],
        "solutions": solutions,
        "solution_cap_reached": bool(cap_reached),
        "no_solutions": len(solutions) == 0,
        "truncated": bool(truncated),
    }
    return payload


def maybe_write_visualization(
    *,
    algorithm_input: str,
    selected_family: str,
    per_iteration_inputs: list[dict[str, Path]],
    baseline_first_outputs: list[str],
    baseline_all_outputs: list[str],
    baseline_binary_path: str | None = None,
) -> None:
    if selected_family not in {"vf3", "glasgow"}:
        return
    if algorithm_input == "subgraph" and selected_family == "glasgow":
        return
    if not per_iteration_inputs:
        return

    payloads: list[dict] = []
    for idx, inputs in enumerate(per_iteration_inputs):
        seed_val: int | None = None
        seed_raw = str(inputs.get("seed", Path("")))
        if seed_raw:
            try:
                seed_val = int(seed_raw)
            except ValueError:
                seed_val = None
        if selected_family == "vf3":
            pattern_adj = parse_vf_graph(Path(inputs["vf_pattern"]))
            target_adj = parse_vf_graph(Path(inputs["vf_target"]))
        else:
            pattern_adj = parse_lad_graph(Path(inputs["lad_pattern"]))
            target_adj = parse_lad_graph(Path(inputs["lad_target"]))
        first_out = baseline_first_outputs[idx] if idx < len(baseline_first_outputs) else ""
        all_out = baseline_all_outputs[idx] if idx < len(baseline_all_outputs) else ""
        mapping_sources = [first_out, all_out]
        vis_algorithm = "subgraph" if algorithm_input == "subgraph" else selected_family
        pattern_nodes_hint = parse_pattern_nodes_hint(inputs, selected_family)
        payloads.append(
            build_visualization_iteration(
                algorithm=vis_algorithm,
                pattern_adj=pattern_adj,
                target_adj=target_adj,
                mapping_sources=mapping_sources,
                pattern_nodes_hint=pattern_nodes_hint,
                iteration=idx + 1,
                seed=seed_val,
            )
        )

    if not payloads:
        return

    root = dict(payloads[0])
    root["visualization_iterations"] = payloads
    (OUTPUTS_DIR / "visualization.json").write_text(
        json.dumps(root, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    algorithm_input = str(os.environ.get("ALGORITHM_INPUT", "dijkstra") or "dijkstra").strip().lower()
    via_node_input = str(os.environ.get("VIA_NODE_INPUT", "") or "").strip()
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
    family_display = {
        "dijkstra": "Dijkstra",
        "sp_via": "With Intermediate",
        "vf3": "VF3",
        "glasgow": "Glasgow",
    }

    exit_code = 0
    started = time.perf_counter()
    timings_ms: dict[str, float] = {}
    timings_ms_stdev: dict[str, float] = {}
    memory_kb: dict[str, int] = {}
    memory_kb_stdev: dict[str, int] = {}
    match_counts: dict[str, dict] = {}
    witness_counts: dict[str, dict] = {}
    statistical_tests: dict = {"metric": "runtime_ms", "alpha": 0.05, "pairs": [], "notes": []}
    variant_metadata: list[dict] = []
    output_lines: list[str] = []
    vis_path = OUTPUTS_DIR / "visualization.json"
    if not (algorithm_input == "subgraph" and subgraph_phase == "glasgow"):
        try:
            if vis_path.is_file():
                vis_path.unlink()
        except OSError:
            pass

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

        mode_order = ["single"] if selected_family in {"dijkstra", "sp_via"} else ["first", "all"]
        per_solver_times: dict[tuple[str, str], list[float]] = {
            (row.variant_id, mode): [] for row in by_role for mode in mode_order
        }
        per_solver_mem: dict[tuple[str, str], list[int]] = {
            (row.variant_id, mode): [] for row in by_role for mode in mode_order
        }
        per_solver_outputs: dict[tuple[str, str], list[str]] = {
            (row.variant_id, mode): [] for row in by_role for mode in mode_order
        }
        per_iteration_inputs: list[dict[str, Path]] = []
        first_only_fallback_rows: set[str] = set()

        for iter_idx in range(iterations):
            if input_mode == "generate":
                inputs = generate_inputs_for_iteration(
                    algorithm=algorithm_input if algorithm_input in {"dijkstra", "sp_via"} else "subgraph",
                    iteration_index=iter_idx,
                    n=n,
                    k=k,
                    density=density,
                    base_seed=base_seed,
                )
            else:
                inputs = get_premade_inputs(selected_family, input_files)
            per_iteration_inputs.append(dict(inputs))

            for row in by_role:
                commands = make_mode_commands(row, inputs, via_label=via_node_input)
                for mode in mode_order:
                    command = commands.get(mode)
                    if command is None:
                        command = commands.get("all") or commands.get("first") or next(iter(commands.values()))
                    print(
                        f"[dynamic] family={selected_family} iter={iter_idx + 1}/{iterations} "
                        f"variant={row.variant_id} mode={mode} warmup={warmup}",
                        flush=True,
                    )

                    if iter_idx == 0:
                        for _ in range(warmup):
                            dur_ms, peak_kb, stdout, stderr, rc = run_with_peak_rss(command)
                            if (
                                rc != 0
                                and mode == "first"
                                and row.family == "vf3"
                                and row.role != "baseline"
                                and "--first-only" in command
                            ):
                                fallback_cmd = [part for part in command if part != "--first-only"]
                                fdur, fpeak, fout, ferr, frc = run_with_peak_rss(fallback_cmd)
                                if frc == 0:
                                    command = fallback_cmd
                                    dur_ms, peak_kb, stdout, stderr, rc = fdur, fpeak, fout, ferr, frc
                                    first_only_fallback_rows.add(row.variant_id)
                            if rc != 0:
                                raise RuntimeError(
                                    build_process_error(
                                        "Warmup failed",
                                        row=row,
                                        command=command,
                                        rc=rc,
                                        stdout=stdout,
                                        stderr=stderr,
                                    )
                                )

                    dur_ms, peak_kb, stdout, stderr, rc = run_with_peak_rss(command)
                    if (
                        rc != 0
                        and mode == "first"
                        and row.family == "vf3"
                        and row.role != "baseline"
                        and "--first-only" in command
                    ):
                        fallback_cmd = [part for part in command if part != "--first-only"]
                        fdur, fpeak, fout, ferr, frc = run_with_peak_rss(fallback_cmd)
                        if frc == 0:
                            command = fallback_cmd
                            dur_ms, peak_kb, stdout, stderr, rc = fdur, fpeak, fout, ferr, frc
                            first_only_fallback_rows.add(row.variant_id)

                    if rc != 0:
                        raise RuntimeError(
                            build_process_error(
                                "Run failed",
                                row=row,
                                command=command,
                                rc=rc,
                                stdout=stdout,
                                stderr=stderr,
                            )
                        )
                    per_solver_times[(row.variant_id, mode)].append(dur_ms)
                    per_solver_mem[(row.variant_id, mode)].append(peak_kb)
                    per_solver_outputs[(row.variant_id, mode)].append((stdout or "") + ("\n" + stderr if stderr else ""))

        for row in by_role:
            key = build_variant_metric_key(row)
            if selected_family in {"dijkstra", "sp_via"}:
                median_ms, stdev_ms = median_and_stdev(per_solver_times[(row.variant_id, "single")])
                median_kb, stdev_kb = median_and_stdev([float(v) for v in per_solver_mem[(row.variant_id, "single")]])
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
                median_first_ms, stdev_first_ms = median_and_stdev(per_solver_times[(row.variant_id, "first")])
                median_all_ms, stdev_all_ms = median_and_stdev(per_solver_times[(row.variant_id, "all")])
                median_first_kb, stdev_first_kb = median_and_stdev([float(v) for v in per_solver_mem[(row.variant_id, "first")]])
                median_all_kb, stdev_all_kb = median_and_stdev([float(v) for v in per_solver_mem[(row.variant_id, "all")]])
                prefix = key
                if algorithm_input == "subgraph":
                    prefix = f"{selected_family}_{prefix}"
                key_first = f"{prefix}_first"
                key_all = f"{prefix}_all"
                if median_first_ms is not None:
                    timings_ms[key_first] = float(median_first_ms)
                    timings_ms_stdev[key_first] = float(stdev_first_ms)
                if median_all_ms is not None:
                    timings_ms[key_all] = float(median_all_ms)
                    timings_ms_stdev[key_all] = float(stdev_all_ms)
                if median_first_kb is not None:
                    memory_kb[key_first] = int(round(median_first_kb))
                    memory_kb_stdev[key_first] = int(round(stdev_first_kb))
                if median_all_kb is not None:
                    memory_kb[key_all] = int(round(median_all_kb))
                    memory_kb_stdev[key_all] = int(round(stdev_all_kb))
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

        solution_counts_by_variant: dict[str, list[str]] = {}
        comparison_reference_label: str | None = None
        comparison_reference_counts: list[int | None] = []
        if selected_family in {"dijkstra", "sp_via"}:
            baseline_outputs = per_solver_outputs[(baseline_row.variant_id, "single")]
        else:
            baseline_outputs = per_solver_outputs[(baseline_row.variant_id, "all")]
            if not baseline_outputs:
                baseline_outputs = per_solver_outputs[(baseline_row.variant_id, "first")]
            baseline_counts_values: list[int | None] = []
            for out in baseline_outputs:
                c = parse_solution_count(out)
                baseline_counts_values.append(c)
            baseline_counts = [str(c) if c is not None else "NA" for c in baseline_counts_values]
            solution_counts_by_variant[baseline_row.variant_id] = baseline_counts
            comparison_reference_counts = list(baseline_counts_values)
            comparison_reference_label = baseline_row.label

            # In combined subgraph mode, use VF3 baseline (phase 1) as the correctness reference.
            if algorithm_input == "subgraph" and selected_family != "vf3":
                vf3_counts = load_previous_vf3_baseline_counts(iterations)
                if vf3_counts and any(v is not None for v in vf3_counts):
                    comparison_reference_counts = vf3_counts
                    comparison_reference_label = "VF3 Baseline (phase 1)"

        for row in by_role:
            if row.role == "baseline":
                continue
            if selected_family in {"dijkstra", "sp_via"}:
                total = 0
                matches = 0
                for i, out in enumerate(per_solver_outputs[(row.variant_id, "single")]):
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
                row_outputs = per_solver_outputs[(row.variant_id, "all")]
                if not row_outputs:
                    row_outputs = per_solver_outputs[(row.variant_id, "first")]
                row_counts = []
                for i, out in enumerate(row_outputs):
                    parsed_count = parse_solution_count(out)
                    row_counts.append(str(parsed_count) if parsed_count is not None else "NA")
                    if i >= len(comparison_reference_counts):
                        continue
                    left = comparison_reference_counts[i]
                    right = parsed_count
                    if left is None or right is None:
                        continue
                    total += 1
                    if left == right:
                        matches += 1
                mismatches = max(0, total - matches)
                solution_counts_by_variant[row.variant_id] = row_counts
            key = row.llm_key or row.variant_id
            if algorithm_input == "subgraph":
                key = row.variant_id
            match_counts[key] = {"matches": matches, "total": total, "mismatches": mismatches}

        if selected_family == "glasgow":
            graph_cache: dict[int, tuple[list[list[int]], list[list[int]]]] = {}

            def get_iteration_lad_graphs(iteration_idx: int) -> tuple[list[list[int]], list[list[int]]]:
                cached = graph_cache.get(iteration_idx)
                if cached is not None:
                    return cached
                inputs = per_iteration_inputs[iteration_idx]
                pattern_path = Path(inputs["lad_pattern"])
                target_path = Path(inputs["lad_target"])
                pattern_adj = parse_lad_graph(pattern_path)
                target_adj = parse_lad_graph(target_path)
                cached = (pattern_adj, target_adj)
                graph_cache[iteration_idx] = cached
                return cached

            total_iterations = min(iterations, len(per_iteration_inputs))
            for row in by_role:
                if row.role == "baseline":
                    continue
                key = row.llm_key or row.variant_id
                if algorithm_input == "subgraph":
                    key = row.variant_id

                first_outputs = list(per_solver_outputs.get((row.variant_id, "first"), []))
                all_outputs = list(per_solver_outputs.get((row.variant_id, "all"), []))

                required = 0
                valid = 0
                parsed = 0
                missing_iterations: list[int] = []
                errors: list[str] = []

                for i in range(total_iterations):
                    first_text = first_outputs[i] if i < len(first_outputs) else ""
                    all_text = all_outputs[i] if i < len(all_outputs) else first_text
                    count = parse_solution_count(all_text)
                    if count is None:
                        count = parse_solution_count(first_text)
                    if count is None or count <= 0:
                        continue

                    required += 1
                    try:
                        pattern_adj, target_adj = get_iteration_lad_graphs(i)
                        has_valid, parsed_now, _valid_now = evaluate_witness_mapping_output(
                            first_text,
                            pattern_adj=pattern_adj,
                            target_adj=target_adj,
                            limit=64,
                        )
                        parsed += int(parsed_now)
                        if has_valid:
                            valid += 1
                        else:
                            missing_iterations.append(i + 1)
                    except Exception as exc:
                        missing_iterations.append(i + 1)
                        errors.append(f"iteration {i + 1}: {exc}")

                witness_counts[key] = {
                    "valid": valid,
                    "required": required,
                    "missing": max(0, required - valid),
                    "parsed_mappings": parsed,
                    "missing_iterations": missing_iterations,
                }
                if errors:
                    witness_counts[key]["errors"] = errors

        statistical_tests = build_runtime_statistical_tests(
            by_role=by_role,
            baseline_row=baseline_row,
            selected_family=selected_family,
            per_solver_times=per_solver_times,
            alpha=0.05,
        )

        if selected_family in {"vf3", "glasgow"}:
            try:
                maybe_write_visualization(
                    algorithm_input=algorithm_input,
                    selected_family=selected_family,
                    per_iteration_inputs=per_iteration_inputs,
                    baseline_first_outputs=per_solver_outputs.get((baseline_row.variant_id, "first"), []),
                    baseline_all_outputs=per_solver_outputs.get((baseline_row.variant_id, "all"), []),
                    baseline_binary_path=baseline_row.binary_path,
                )
            except Exception as vis_exc:
                output_lines.append(f"[visualization warning] {vis_exc}")
                output_lines.append("")

        algo_header = "WITH INTERMEDIATE" if algorithm_input == "sp_via" else algorithm_input.upper()
        output_lines.append(f"[{algo_header} Dynamic Runner]")
        output_lines.append(f"Family: {family_display.get(selected_family, selected_family)}")
        output_lines.append(f"Iterations: {iterations}")
        output_lines.append(f"Warmup: {warmup}")
        output_lines.append(f"Seed used: {base_seed}")
        if via_node_input:
            output_lines.append(f"Via node: {via_node_input}")
        if comparison_reference_label and comparison_reference_label != baseline_row.label:
            output_lines.append(f"Equivalence reference: {comparison_reference_label}")
        if first_only_fallback_rows:
            output_lines.append(
                "First-only fallback used for: "
                + ", ".join(sorted(first_only_fallback_rows))
            )
        if skipped_rows:
            output_lines.append(f"Skipped optional variants: {len(skipped_rows)}")
            for item in skipped_rows:
                output_lines.append(f"  - {item}")
        output_lines.append("")
        stats_rows = list(statistical_tests.get("pairs", []))
        if stats_rows:
            output_lines.append("Runtime Statistical Tests (variant vs baseline):")
            output_lines.append(
                "  blurb: Paired t-test checks if the average runtime delta is non-random; "
                "Mann-Whitney U checks distribution shift; effect sizes show practical magnitude."
            )
            for row in stats_rows:
                if not isinstance(row, dict):
                    continue
                n = int(row.get("n", 0) or 0)
                mode = str(row.get("mode") or "single")
                label = str(row.get("variant_label") or row.get("variant_id") or "variant")
                baseline_label = str(row.get("baseline_label") or row.get("baseline_variant_id") or "baseline")
                if n <= 0:
                    output_lines.append(f"  - [{mode}] {label} vs {baseline_label}: insufficient matched samples (n=0).")
                    continue
                mean_delta = row.get("mean_delta_ms")
                direction = str(row.get("direction") or "n/a")
                paired = row.get("paired_t_test") if isinstance(row.get("paired_t_test"), dict) else {}
                p_value = paired.get("p_value_two_sided")
                p_text = "n/a" if p_value is None else f"{float(p_value):.6g}"
                effect_sizes = row.get("effect_sizes") if isinstance(row.get("effect_sizes"), dict) else {}
                hedges_g = effect_sizes.get("hedges_g")
                g_text = "n/a" if hedges_g is None else f"{float(hedges_g):.4f}"
                output_lines.append(
                    f"  - [{mode}] {label} vs {baseline_label}: n={n}, mean_delta={float(mean_delta):.3f} ms, "
                    f"direction={direction}, p={p_text}, hedges_g={g_text}"
                )
            output_lines.append("")

        if algorithm_input in {"dijkstra", "sp_via"}:
            for row in by_role:
                metric_key = build_variant_metric_key(row)
                output_lines.append(f"[{row.label}]")
                output_lines.append(
                    fmt_labeled_median_stdev(
                        "Runtime (ms)",
                        timings_ms.get(metric_key),
                        timings_ms_stdev.get(metric_key),
                    )
                )
                output_lines.append(
                    fmt_labeled_median_stdev(
                        "Peak RSS (KB)",
                        memory_kb.get(metric_key),
                        memory_kb_stdev.get(metric_key),
                    )
                )
                output_lines.append(
                    fmt_labeled_value(
                        "Samples",
                        str(len(per_solver_times.get((row.variant_id, "single"), []))),
                    )
                )
                output_lines.append("")
        else:
            for row in by_role:
                key = build_variant_metric_key(row)
                metric_prefix = key
                if algorithm_input == "subgraph":
                    metric_prefix = f"{selected_family}_{metric_prefix}"

                output_lines.append(f"[{row.label}]")
                if row.role != "baseline":
                    match_key = row.llm_key or row.variant_id
                    if algorithm_input == "subgraph":
                        match_key = row.variant_id
                    match_row = match_counts.get(match_key)
                    if isinstance(match_row, dict):
                        matched = match_row.get("matches", "n/a")
                        total = match_row.get("total", "n/a")
                        mismatches = match_row.get("mismatches", "n/a")
                        output_lines.append(
                            fmt_labeled_value(
                                "Equivalence",
                                f"{matched}/{total} matched ({mismatches} mismatches)",
                            )
                        )
                    witness_row = witness_counts.get(match_key)
                    if isinstance(witness_row, dict):
                        witness_valid = witness_row.get("valid", "n/a")
                        witness_required = witness_row.get("required", "n/a")
                        witness_missing = witness_row.get("missing", "n/a")
                        output_lines.append(
                            fmt_labeled_value(
                                "Witness mapping",
                                f"{witness_valid}/{witness_required} valid ({witness_missing} missing)",
                            )
                        )
                        missing_iters = witness_row.get("missing_iterations")
                        if isinstance(missing_iters, list) and missing_iters:
                            output_lines.append(
                                fmt_labeled_value(
                                    "Witness missing Iters",
                                    ",".join(str(int(x)) for x in missing_iters[:12]),
                                )
                            )
                output_lines.append(
                    fmt_labeled_median_stdev(
                        "Runtime First (ms)",
                        timings_ms.get(f"{metric_prefix}_first"),
                        timings_ms_stdev.get(f"{metric_prefix}_first"),
                    )
                )
                output_lines.append(
                    fmt_labeled_median_stdev(
                        "Runtime All (ms)",
                        timings_ms.get(f"{metric_prefix}_all"),
                        timings_ms_stdev.get(f"{metric_prefix}_all"),
                    )
                )
                output_lines.append(
                    fmt_labeled_median_stdev(
                        "Peak RSS First (KB)",
                        memory_kb.get(f"{metric_prefix}_first"),
                        memory_kb_stdev.get(f"{metric_prefix}_first"),
                    )
                )
                output_lines.append(
                    fmt_labeled_median_stdev(
                        "Peak RSS All (KB)",
                        memory_kb.get(f"{metric_prefix}_all"),
                        memory_kb_stdev.get(f"{metric_prefix}_all"),
                    )
                )
                output_lines.append(
                    fmt_labeled_value(
                        "Samples (first/all)",
                        f"{len(per_solver_times.get((row.variant_id, 'first'), []))}/"
                        f"{len(per_solver_times.get((row.variant_id, 'all'), []))}",
                    )
                )
                output_lines.append("")

            count_headers = ["Variant"] + [f"I{i + 1}" for i in range(iterations)]
            count_rows: list[list[str]] = []
            for row in by_role:
                counts = solution_counts_by_variant.get(row.variant_id, [])
                padded = list(counts) + ["NA"] * max(0, iterations - len(counts))
                count_rows.append([row.label, *padded[:iterations]])
            output_lines.append("Solution Counts Per Iteration:")
            output_lines.extend(render_ascii_table(count_headers, count_rows))
            output_lines.append("")

            # Keep this explicit format so the visualizer's count parser can read it.
            for row in by_role:
                counts = solution_counts_by_variant.get(row.variant_id, [])
                if not counts:
                    continue
                output_lines.append(f"[{row.label}]")
                output_lines.append(f"Solution counts: [{', '.join(counts)}]")
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
        "VIA_NODE_INPUT": via_node_input,
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
        "WITNESS_COUNTS_JSON": json.dumps(witness_counts, separators=(",", ":"), sort_keys=True),
        "STATISTICAL_TESTS_JSON": json.dumps(statistical_tests, separators=(",", ":"), sort_keys=True),
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
