#!/usr/bin/env python3
"""Capstone desktop benchmark runner (cross-platform, one-file packaged app)."""

# - This is the desktop application's integration point: Tk UI state, dataset
#   preparation, local execution, packaging support, and session export all
#   converge here.
# - Shared behavior should stay aligned with desktop_runner.headless_runner and
#   utilities/* helpers; schema or seed changes usually need updates in more
#   than one entrypoint.
# - Prefer extracting reusable logic into smaller helpers instead of deepening
#   callback-to-callback coupling inside this file.

from __future__ import annotations

import csv
import concurrent.futures
import datetime as dt
import importlib.util
import argparse
import gzip
import hashlib
import io
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path

import psutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from utilities import generate_graphs as generator_mod
from utilities.benchmark_provenance import collect_runtime_provenance

try:
    import winreg  # type: ignore
except Exception:
    winreg = None  # type: ignore

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

try:
    if sys.platform.startswith("win"):
        from tkwebview2.tkwebview2 import WebView2 as TkWebView2, have_runtime as webview2_runtime_available
    else:
        TkWebView2 = None
        webview2_runtime_available = None
except Exception:
    TkWebView2 = None
    webview2_runtime_available = None

APP_TITLE = "Capstone Benchmark Runner"
DEFAULT_WIDTH = 1500
DEFAULT_HEIGHT = 980
DEFAULT_DISCARDED_WARMUP_TRIALS = 5
DEFAULT_OUTLIER_MIN_SAMPLES = 7
DEFAULT_3D_ELEV = 30.0
# Keep x=min and y=min corner toward the viewer in the default isometric view.
DEFAULT_3D_AZIM = -135.0
LOG_COLOR_TAGS = ("info", "error", "warn", "success", "notice")

THEME_PALETTES = {
    "light": {
        "bg": "#F4F6F8",
        "panel_bg": "#FFFFFF",
        "fg": "#1F2933",
        "muted_fg": "#5F6B76",
        "border": "#D6DCE3",
        "input_bg": "#FFFFFF",
        "button_bg": "#E8EDF3",
        "button_active_bg": "#DCE5EE",
        "tab_bg": "#E8EDF3",
        "tab_selected_bg": "#FFFFFF",
        "accent": "#0B5CAD",
        "text_bg": "#FFFFFF",
        "text_fg": "#222222",
        "select_bg": "#CCE2F8",
        "select_fg": "#102A43",
        "tooltip_bg": "#FFFBE6",
        "tooltip_fg": "#222222",
        "value_active_fg": "#222222",
        "value_disabled_fg": "#888888",
        "log_info": "#222222",
        "log_warn": "#9A6700",
        "log_error": "#B00020",
        "log_success": "#0A7D32",
        "log_notice": "#0B5CAD",
    },
    "dark": {
        "bg": "#1B1E24",
        "panel_bg": "#242933",
        "fg": "#E6EAF0",
        "muted_fg": "#B7C0CC",
        "border": "#3A4352",
        "input_bg": "#1F2430",
        "button_bg": "#313949",
        "button_active_bg": "#3A4458",
        "tab_bg": "#2B3240",
        "tab_selected_bg": "#3A4458",
        "accent": "#4FA3FF",
        "text_bg": "#171B22",
        "text_fg": "#E6EAF0",
        "select_bg": "#2D4E78",
        "select_fg": "#EAF2FF",
        "tooltip_bg": "#2A2F3A",
        "tooltip_fg": "#E6EAF0",
        "value_active_fg": "#E6EAF0",
        "value_disabled_fg": "#8694A6",
        "log_info": "#E6EAF0",
        "log_warn": "#F6C667",
        "log_error": "#FF8A9A",
        "log_success": "#67D99A",
        "log_notice": "#7BC0FF",
    },
}


def resource_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def adjacent_output_base() -> Path:
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        return exe_path.parent
    return Path(__file__).resolve().parent.parent


def make_session_output_dir() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = adjacent_output_base()
    target = base / f"benchmark_output_{stamp}"
    target.mkdir(parents=True, exist_ok=True)
    return target


def parse_int(value: str, name: str, minimum: int | None = None) -> int:
    raw = str(value).strip()
    if raw == "":
        raise ValueError(f"{name} is required")
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def parse_float(value: str, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = str(value).strip()
    if raw == "":
        raise ValueError(f"{name} is required")
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return parsed


def build_range(start: float, end: float, step: float, *, integer_mode: bool) -> list[float]:
    if step <= 0:
        raise ValueError("Step must be > 0")
    if end < start:
        raise ValueError("End must be >= start")
    values: list[float] = []
    current = start
    guard = 0
    while current <= end + 1e-12:
        values.append(round(current, 10))
        current += step
        guard += 1
        if guard > 500000:
            raise ValueError("Range is too large")
    if integer_mode:
        return [float(int(round(v))) for v in values]
    return values


def safe_stdev(samples: list[float]) -> float:
    if len(samples) < 2:
        return 0.0
    return float(statistics.stdev(samples))


def median_or_none(samples: list[float]) -> float | None:
    if not samples:
        return None
    return float(statistics.median(samples))


def linear_regression_line(xs: list[float], ys: list[float]):
    if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
        return None
    n = float(len(xs))
    sum_x = float(sum(xs))
    sum_y = float(sum(ys))
    sum_xx = float(sum(x * x for x in xs))
    sum_xy = float(sum(x * y for x, y in zip(xs, ys)))
    denom = (n * sum_xx) - (sum_x * sum_x)
    if abs(denom) < 1e-12:
        return None
    slope = ((n * sum_xy) - (sum_x * sum_y)) / denom
    intercept = (sum_y - (slope * sum_x)) / n
    sorted_x = sorted(float(x) for x in xs)
    reg_y = [(slope * x) + intercept for x in sorted_x]
    return sorted_x, reg_y


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return math.nan
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    q = max(0.0, min(1.0, float(q)))
    pos = q * float(len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - float(lo)
    return (float(sorted_values[lo]) * (1.0 - frac)) + (float(sorted_values[hi]) * frac)


def filter_outlier_samples(samples: list[float], mode: str, min_samples: int = DEFAULT_OUTLIER_MIN_SAMPLES) -> list[float]:
    values = [float(v) for v in (samples or []) if isinstance(v, (int, float)) and math.isfinite(float(v))]
    if len(values) < max(1, int(min_samples)):
        return values

    mode_key = str(mode or "none").strip().lower()
    if mode_key in {"", "none"}:
        return values

    if mode_key == "mad":
        center = float(statistics.median(values))
        deviations = [abs(v - center) for v in values]
        mad = float(statistics.median(deviations))
        if mad <= 0.0:
            return values
        sigma_estimate = 1.4826 * mad
        threshold = 3.0 * sigma_estimate
        filtered = [v for v in values if abs(v - center) <= threshold]
        return filtered or values

    if mode_key == "iqr":
        ordered = sorted(values)
        q1 = percentile(ordered, 0.25)
        q3 = percentile(ordered, 0.75)
        iqr = float(q3 - q1)
        if not math.isfinite(iqr) or iqr <= 0.0:
            return values
        low = q1 - (1.5 * iqr)
        high = q3 + (1.5 * iqr)
        filtered = [v for v in values if low <= v <= high]
        return filtered or values

    return values


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

    # For very large df the normal approximation is accurate and cheaper.
    if df >= 200:
        tail = 0.5 * math.erfc(x / math.sqrt(2.0))
        return max(0.0, min(1.0, 2.0 * tail))

    # Student-t PDF normalizing constant.
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
    sd_delta = float(statistics.stdev(deltas)) if pair_count >= 2 else 0.0

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


def build_desktop_runtime_statistical_tests(
    *,
    config: dict,
    point_states: dict[int, dict],
    selected_variants: list[str],
    alpha: float = 0.05,
) -> dict:
    family_to_baseline = {
        "vf3": "vf3_baseline",
        "glasgow": "glasgow_baseline",
        "dijkstra": "dijkstra_baseline",
        "sp_via": "sp_via_baseline",
    }
    pair_samples: dict[str, dict[str, list[float] | str]] = {}
    for variant_id in selected_variants:
        if variant_id.endswith("_baseline"):
            continue
        family = variant_family_from_id(variant_id)
        baseline_variant_id = family_to_baseline.get(family)
        if not baseline_variant_id:
            continue
        pair_samples[variant_id] = {
            "baseline_variant_id": baseline_variant_id,
            "variant_samples": [],
            "baseline_samples": [],
        }

    for state in point_states.values():
        iter_runtime_ms = state.get("iter_runtime_ms", {})
        if not isinstance(iter_runtime_ms, dict):
            continue
        for iter_idx in range(int(config.get("iterations", 0))):
            iter_map = iter_runtime_ms.get(iter_idx, {})
            if not isinstance(iter_map, dict):
                continue
            for variant_id, holder in pair_samples.items():
                baseline_variant_id = str(holder.get("baseline_variant_id", "") or "")
                baseline_runtime = iter_map.get(baseline_variant_id)
                solver_runtime = iter_map.get(variant_id)
                if baseline_runtime is None or solver_runtime is None:
                    continue
                holder["baseline_samples"].append(float(baseline_runtime))
                holder["variant_samples"].append(float(solver_runtime))

    label_lookup = dict(config.get("selected_variant_labels", {}) or {})
    rows: list[dict] = []
    for variant_id in selected_variants:
        holder = pair_samples.get(variant_id)
        if not isinstance(holder, dict):
            continue
        baseline_variant_id = str(holder.get("baseline_variant_id", "") or "")
        summary = summarize_runtime_comparison(
            variant_samples_ms=list(holder.get("variant_samples", [])),
            baseline_samples_ms=list(holder.get("baseline_samples", [])),
            alpha=alpha,
        )
        rows.append(
            {
                "variant_id": variant_id,
                "variant_label": str(label_lookup.get(variant_id, variant_id)),
                "baseline_variant_id": baseline_variant_id,
                "baseline_label": str(label_lookup.get(baseline_variant_id, baseline_variant_id)),
                "mode": "single",
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


def number_or_blank(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.6f}"


def axis_label(var_id: str) -> str:
    if var_id == "n":
        return "N (nodes)"
    if var_id == "density":
        return "Density"
    if var_id == "k":
        return "k % of N"
    return var_id


def format_point_value(var_id: str, value: float) -> str:
    if var_id == "n":
        return str(int(round(value)))
    if var_id == "k":
        return f"{value:.2f}%"
    return f"{value:.4f}"


def format_step_value(var_id: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    if var_id == "n":
        return str(int(round(value)))
    if var_id == "k":
        return f"{value:.2f}%"
    return f"{value:.4f}"


def parse_solution_count(output_text: str) -> int | None:
    text = (output_text or "").strip()
    if text == "":
        return None
    patterns = [
        r"(?im)\bsolution[_\s-]*count\s*[:=]\s*(-?\d+)\b",
        r"(?im)\bsolutions?\s*(?:count|found|total)?\s*[:=]\s*(-?\d+)\b",
        r"(?im)\bcount\s*[:=]\s*(-?\d+)\b",
        r"(?im)\b(-?\d+)\s+solutions?\b",
        r"(?im)\bmatches?\s*[:=]\s*(-?\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                continue

    stripped = [line.strip() for line in text.splitlines() if line.strip()]
    for line in stripped:
        # VF3 baseline terse mode prints: "<solutions> <first_time> <all_time>"
        # Parse the leading integer as the solution count.
        terse = re.fullmatch(
            r"\s*(-?\d+)\s+[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s+[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*",
            line,
        )
        if terse:
            try:
                return int(terse.group(1))
            except Exception:
                pass

    if len(stripped) == 1 and re.fullmatch(r"-?\d+", stripped[0]):
        return int(stripped[0])

    return None


def parse_dijkstra_distance(output_text: str) -> str | None:
    text = (output_text or "").strip()
    if text == "":
        return None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "":
            continue
        if re.match(r"(?i)^runtime\s*:", line):
            continue

        token = line.split(";", 1)[0].strip()
        if token == "":
            continue
        token_upper = token.upper()
        if token_upper in {"INF", "INFINITY"}:
            return "INF"
        if token == "-1":
            return "INF"
        if re.fullmatch(r"[+-]?\d+", token):
            try:
                value = int(token)
            except Exception:
                continue
            if value < 0:
                return "INF"
            return str(value)

        match = re.search(r"(?i)\bdistance\s*[:=]\s*([+-]?\d+|INF|INFINITY)\b", line)
        if match:
            raw_value = str(match.group(1)).strip()
            raw_upper = raw_value.upper()
            if raw_upper in {"INF", "INFINITY"}:
                return "INF"
            try:
                parsed = int(raw_value)
            except Exception:
                continue
            if parsed < 0:
                return "INF"
            return str(parsed)

    return None


VISUALIZER_SOLUTION_CAP = 2000
VISUALIZER_PREFETCH_RADIUS = 10


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
            v = int(edge_tokens[1]) if len(edge_tokens) >= 2 else int(edge_tokens[0])
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


def extract_mappings_from_text(text: str, limit: int = VISUALIZER_SOLUTION_CAP) -> list[dict[int, int]]:
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
    limit: int = VISUALIZER_SOLUTION_CAP,
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


def serialize_for_json(obj):
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat()
    raise TypeError(f"Unsupported type for JSON serialization: {type(obj)!r}")


def compute_triangle_normal(p1, p2, p3):
    ux, uy, uz = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
    vx, vy, vz = (p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2])
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if norm == 0:
        return (0.0, 0.0, 0.0)
    return (nx / norm, ny / norm, nz / norm)


def write_ascii_stl(path: Path, solid_name: str, triangles):
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"solid {solid_name}\n")
        for p1, p2, p3 in triangles:
            nx, ny, nz = compute_triangle_normal(p1, p2, p3)
            fh.write(f"  facet normal {nx:.8e} {ny:.8e} {nz:.8e}\n")
            fh.write("    outer loop\n")
            fh.write(f"      vertex {p1[0]:.8e} {p1[1]:.8e} {p1[2]:.8e}\n")
            fh.write(f"      vertex {p2[0]:.8e} {p2[1]:.8e} {p2[2]:.8e}\n")
            fh.write(f"      vertex {p3[0]:.8e} {p3[1]:.8e} {p3[2]:.8e}\n")
            fh.write("    endloop\n")
            fh.write("  endfacet\n")
        fh.write(f"endsolid {solid_name}\n")


def has_pywebview() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def run_visualizer_webview_window(url: str, title: str, fullscreen: bool = False) -> int:
    try:
        import webview
    except Exception as exc:
        print(f"pywebview is unavailable: {exc}", file=sys.stderr)
        return 2

    try:
        webview.create_window(
            str(title or "Benchmark Visualizer"),
            url=str(url or ""),
            width=1280,
            height=840,
            fullscreen=bool(fullscreen),
        )
        webview.start()
        return 0
    except Exception as exc:
        print(f"Failed to open desktop webview: {exc}", file=sys.stderr)
        return 3


class RunAbortedError(RuntimeError):
    pass


class SolverTimeoutError(RuntimeError):
    def __init__(self, timeout_seconds: float, elapsed_seconds: float):
        super().__init__(f"Solver timed out after {elapsed_seconds:.1f}s (limit {timeout_seconds:.1f}s)")
        self.timeout_seconds = float(timeout_seconds)
        self.elapsed_seconds = float(elapsed_seconds)


@dataclass(frozen=True)
class SolverVariant:
    variant_id: str
    label: str
    tab_id: str
    family: str
    role: str


@dataclass
class DatapointStats:
    x_value: float
    y_value: float | None
    runtime_median_ms: float | None
    runtime_stdev_ms: float
    runtime_samples_n: int
    memory_median_kb: float | None
    memory_stdev_kb: float
    memory_samples_n: int
    completed_iterations: int
    requested_iterations: int
    seeds: list[int]


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    name: str
    tab_id: str
    source: str
    source_url: str
    raw_format: str
    description: str
    estimated_size_bytes: int
    estimated_graph_files: int
    estimated_pair_count: int
    download: dict
    prepare: dict


DEFAULT_DATASET_CATALOG_ROWS = [
    {
        "dataset_id": "subgraph_sip_full",
        "name": "SIP Full Archive",
        "tab_id": "subgraph",
        "source": "SIP Benchmarks (Solnon)",
        "source_url": "https://perso.citi-lab.fr/csolnon/SIP.html",
        "raw_format": "TGZ archive of subgraph benchmark suites",
        "description": "Large benchmark archive containing multiple subgraph isomorphism suites (si, scalefree, image, mesh, etc.).",
        "estimated_size_bytes": 27882629,
        "estimated_graph_files": 8294,
        "estimated_pair_count": 1170,
        "download": {
            "kind": "single_file",
            "url": "http://perso.citi-lab.fr/csolnon/newSIPbenchmarks.tgz",
            "relative_path": "raw/newSIPbenchmarks.tgz",
        },
        "prepare": {
            "kind": "subgraph_pair_from_tgz_members",
            "archive_relative_path": "raw/newSIPbenchmarks.tgz",
            "pattern_member": "newSIPbenchmarks/si/si2_bvg_b03m_200/si2_b03m_m200.04/pattern",
            "target_member": "newSIPbenchmarks/si/si2_bvg_b03m_200/si2_b03m_m200.04/target",
        },
    },
    {
        "dataset_id": "subgraph_mivia_arg",
        "name": "MIVIA ARG Database",
        "tab_id": "subgraph",
        "source": "MIVIA",
        "source_url": "https://mivia.unisa.it/datasets/graph-database/arg-database/",
        "raw_format": "ZIP archive (binary graph files + gtr files)",
        "description": "Large ARG benchmark collection (binary format). A representative non-induced subgraph pair is converted on demand after download.",
        "estimated_size_bytes": 418262348,
        "estimated_graph_files": 143600,
        "estimated_pair_count": 168000,
        "download": {
            "kind": "single_file",
            "url": "https://mivia.unisa.it/database/graphsdb.zip",
            "relative_path": "raw/graphsdb.zip",
        },
        "prepare": {
            "kind": "subgraph_pair_from_mivia_archive",
            "archive_relative_path": "raw/graphsdb.zip",
            "inner_zip_prefix": "si2_",
            "labeled": False,
        },
    },
    {
        "dataset_id": "subgraph_practical_bigraphs",
        "name": "Practical Bigraphs (Zenodo)",
        "tab_id": "subgraph",
        "source": "Zenodo",
        "source_url": "https://zenodo.org/records/4597074",
        "raw_format": "TAR.XZ archive",
        "description": "Practical Bigraphs benchmark archive (11,176 instances). A representative non-induced subgraph pair is converted on demand after download.",
        "estimated_size_bytes": 14312140,
        "estimated_graph_files": 11176,
        "estimated_pair_count": 11176,
        "download": {
            "kind": "single_file",
            "url": "https://zenodo.org/records/4597074/files/instances.tar.xz?download=1",
            "relative_path": "raw/instances.tar.xz",
        },
        "prepare": {
            "kind": "subgraph_pair_from_bigraph_archive",
            "archive_relative_path": "raw/instances.tar.xz",
            "instances_member": "instances/savannah_instances.txt",
        },
    },
    {
        "dataset_id": "shortest_dimacs_usa_road_d",
        "name": "DIMACS USA-road-d",
        "tab_id": "shortest_path",
        "source": "DIMACS Challenge 9",
        "source_url": "https://www.diag.uniroma1.it/challenge9/download.shtml",
        "raw_format": "DIMACS .gr.gz",
        "description": "Full USA road network from DIMACS challenge data (directed, weighted arcs).",
        "estimated_size_bytes": 351265214,
        "estimated_graph_files": 1,
        "estimated_pair_count": 1,
        "download": {
            "kind": "single_file",
            "url": "https://www.diag.uniroma1.it/challenge9/data/USA-road-d/USA-road-d.USA.gr.gz",
            "relative_path": "raw/USA-road-d.USA.gr.gz",
        },
        "prepare": {
            "kind": "shortest_path_csv_from_dimacs_gr_gz",
            "source_relative_path": "raw/USA-road-d.USA.gr.gz",
        },
    },
    {
        "dataset_id": "shortest_snap_roadnet_ca",
        "name": "SNAP roadNet-CA",
        "tab_id": "shortest_path",
        "source": "SNAP",
        "source_url": "https://snap.stanford.edu/data/roadNet-CA.html",
        "raw_format": "Edge-list .txt.gz",
        "description": "California road network graph from SNAP.",
        "estimated_size_bytes": 17892860,
        "estimated_graph_files": 1,
        "estimated_pair_count": 1,
        "download": {
            "kind": "single_file",
            "url": "https://snap.stanford.edu/data/roadNet-CA.txt.gz",
            "relative_path": "raw/roadNet-CA.txt.gz",
        },
        "prepare": {
            "kind": "shortest_path_csv_from_edge_list_gz",
            "source_relative_path": "raw/roadNet-CA.txt.gz",
            "assume_undirected": True,
        },
    },
    {
        "dataset_id": "shortest_snap_roadnet_tx",
        "name": "SNAP roadNet-TX",
        "tab_id": "shortest_path",
        "source": "SNAP",
        "source_url": "https://snap.stanford.edu/data/roadNet-TX.html",
        "raw_format": "Edge-list .txt.gz",
        "description": "Texas road network graph from SNAP.",
        "estimated_size_bytes": 12442024,
        "estimated_graph_files": 1,
        "estimated_pair_count": 1,
        "download": {
            "kind": "single_file",
            "url": "https://snap.stanford.edu/data/roadNet-TX.txt.gz",
            "relative_path": "raw/roadNet-TX.txt.gz",
        },
        "prepare": {
            "kind": "shortest_path_csv_from_edge_list_gz",
            "source_relative_path": "raw/roadNet-TX.txt.gz",
            "assume_undirected": True,
        },
    },
    {
        "dataset_id": "shortest_snap_wiki_talk",
        "name": "SNAP Wiki-Talk",
        "tab_id": "shortest_path",
        "source": "SNAP",
        "source_url": "https://snap.stanford.edu/data/wiki-Talk.html",
        "raw_format": "Edge-list .txt.gz",
        "description": "Wikipedia user talk network from SNAP (directed).",
        "estimated_size_bytes": 16947922,
        "estimated_graph_files": 1,
        "estimated_pair_count": 1,
        "download": {
            "kind": "single_file",
            "url": "https://snap.stanford.edu/data/wiki-Talk.txt.gz",
            "relative_path": "raw/wiki-Talk.txt.gz",
        },
        "prepare": {
            "kind": "shortest_path_csv_from_edge_list_gz",
            "source_relative_path": "raw/wiki-Talk.txt.gz",
            "assume_undirected": False,
        },
    },
    {
        "dataset_id": "shortest_snap_livejournal",
        "name": "SNAP LiveJournal",
        "tab_id": "shortest_path",
        "source": "SNAP",
        "source_url": "https://snap.stanford.edu/data/com-LiveJournal.html",
        "raw_format": "Edge-list .txt.gz",
        "description": "Large LiveJournal social graph from SNAP.",
        "estimated_size_bytes": 124262769,
        "estimated_graph_files": 1,
        "estimated_pair_count": 1,
        "download": {
            "kind": "single_file",
            "url": "https://snap.stanford.edu/data/bigdata/communities/com-lj.ungraph.txt.gz",
            "relative_path": "raw/com-lj.ungraph.txt.gz",
        },
        "prepare": {
            "kind": "shortest_path_csv_from_edge_list_gz",
            "source_relative_path": "raw/com-lj.ungraph.txt.gz",
            "assume_undirected": True,
        },
    },
]


def _dataset_catalog_paths() -> list[Path]:
    paths: list[Path] = []
    root = resource_root()
    paths.append(root / "desktop_runner" / "datasets_catalog.json")
    paths.append(Path(__file__).resolve().with_name("datasets_catalog.json"))
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve() if path.exists() else path).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _normalize_dataset_spec_rows(rows: list[dict]) -> list[DatasetSpec]:
    specs: list[DatasetSpec] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        dataset_id = str(row.get("dataset_id") or "").strip().lower()
        tab_id = str(row.get("tab_id") or "").strip().lower()
        if not dataset_id or tab_id not in {"subgraph", "shortest_path"}:
            continue
        if dataset_id in seen_ids:
            continue
        seen_ids.add(dataset_id)
        specs.append(
            DatasetSpec(
                dataset_id=dataset_id,
                name=str(row.get("name") or dataset_id).strip() or dataset_id,
                tab_id=tab_id,
                source=str(row.get("source") or "").strip(),
                source_url=str(row.get("source_url") or "").strip(),
                raw_format=str(row.get("raw_format") or "").strip(),
                description=str(row.get("description") or "").strip(),
                estimated_size_bytes=int(max(0, int(row.get("estimated_size_bytes") or 0))),
                estimated_graph_files=int(max(0, int(row.get("estimated_graph_files") or 0))),
                estimated_pair_count=int(max(0, int(row.get("estimated_pair_count") or 0))),
                download=dict(row.get("download") or {}),
                prepare=dict(row.get("prepare") or {}),
            )
        )
    specs.sort(key=lambda item: (item.tab_id, item.name.lower(), item.dataset_id))
    return specs


def load_dataset_catalog() -> list[DatasetSpec]:
    for path in _dataset_catalog_paths():
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        rows = payload.get("datasets") if isinstance(payload, dict) else None
        if isinstance(rows, list):
            normalized = _normalize_dataset_spec_rows(rows)
            if normalized:
                return normalized
    return _normalize_dataset_spec_rows(list(DEFAULT_DATASET_CATALOG_ROWS))


def format_bytes_human(num_bytes: int) -> str:
    size = float(max(0, int(num_bytes)))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024.0 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.2f} {units[idx]}"


SUPPORTED_FAMILIES = {"dijkstra", "sp_via", "dial", "vf3", "glasgow"}
FAMILY_LABELS = {
    "dijkstra": "Dijkstra",
    "sp_via": "With Intermediate",
    "dial": "Dial",
    "vf3": "VF3",
    "glasgow": "Glasgow",
}


def variant_family_from_id(variant_id: str) -> str:
    token = str(variant_id or "").strip().lower()
    if token.startswith("sp_via_"):
        return "sp_via"
    if "_" in token:
        return token.split("_", 1)[0]
    return token


def _baseline_solver_rows() -> list[dict]:
    return [
        {"variant_id": "vf3_baseline", "label": "VF3 Baseline", "family": "vf3", "role": "baseline"},
        {"variant_id": "glasgow_baseline", "label": "Glasgow Baseline", "family": "glasgow", "role": "baseline"},
        {"variant_id": "dijkstra_baseline", "label": "Dijkstra Baseline", "family": "dijkstra", "role": "baseline"},
        {"variant_id": "dijkstra_dial", "label": "Dial Benchmark", "family": "dial", "role": "baseline"},
        {"variant_id": "sp_via_baseline", "label": "With Intermediate Baseline", "family": "sp_via", "role": "baseline"},
        {"variant_id": "sp_via_dial", "label": "With Intermediate Dial", "family": "sp_via", "role": "variant", "llm_key": "dial", "llm_label": "Dial"},
    ]


def _legacy_llm_solver_rows() -> list[dict]:
    return [
        {"variant_id": "vf3_chatgpt", "label": "VF3 Chatgpt", "family": "vf3", "role": "variant", "llm_key": "chatgpt", "llm_label": "Chatgpt"},
        {"variant_id": "vf3_gemini", "label": "VF3 Gemini", "family": "vf3", "role": "variant", "llm_key": "gemini", "llm_label": "Gemini"},
        {"variant_id": "glasgow_chatgpt", "label": "Glasgow Chatgpt", "family": "glasgow", "role": "variant", "llm_key": "chatgpt", "llm_label": "Chatgpt"},
        {"variant_id": "glasgow_gemini", "label": "Glasgow Gemini", "family": "glasgow", "role": "variant", "llm_key": "gemini", "llm_label": "Gemini"},
        {"variant_id": "dijkstra_chatgpt", "label": "Dijkstra Chatgpt", "family": "dijkstra", "role": "variant", "llm_key": "chatgpt", "llm_label": "Chatgpt"},
        {"variant_id": "dijkstra_gemini", "label": "Dijkstra Gemini", "family": "dijkstra", "role": "variant", "llm_key": "gemini", "llm_label": "Gemini"},
        {"variant_id": "sp_via_chatgpt", "label": "With Intermediate Chatgpt", "family": "sp_via", "role": "variant", "llm_key": "chatgpt", "llm_label": "Chatgpt"},
        {"variant_id": "sp_via_gemini", "label": "With Intermediate Gemini", "family": "sp_via", "role": "variant", "llm_key": "gemini", "llm_label": "Gemini"},
    ]


def _title_llm_token(token: str) -> str:
    token = str(token or "").strip().lower()
    if token == "chatgpt":
        return "ChatGPT"
    if token == "claude":
        return "Claude"
    if token == "gemini":
        return "Gemini"
    parts = [part for part in token.split("_") if part]
    if not parts:
        return "Unknown"
    return " ".join(part[:1].upper() + part[1:] for part in parts)


def _normalize_solver_rows(rows: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        variant_id = str(row.get("variant_id") or "").strip().lower()
        family = str(row.get("family") or "").strip().lower()
        role = str(row.get("role") or "").strip().lower() or "variant"
        label = str(row.get("label") or variant_id).strip() or variant_id
        llm_key = str(row.get("llm_key") or "").strip().lower() or None
        llm_label = str(row.get("llm_label") or "").strip() or None
        if variant_id == "dijkstra_dial":
            # Treat Dial as a benchmark row in the desktop selector.
            family = "dial"
            role = "baseline"
            label = "Dial Benchmark"
            llm_key = None
            llm_label = None
        if not variant_id or family not in SUPPORTED_FAMILIES:
            continue
        normalized.append(
            {
                "variant_id": variant_id,
                "label": label,
                "family": family,
                "role": role,
                "llm_key": llm_key,
                "llm_label": llm_label,
                "binary_name": str(row.get("binary_name") or "").strip() or variant_id,
            }
        )
    return normalized


def _repo_root_candidates() -> list[Path]:
    seen: set[str] = set()
    candidates: list[Path] = []
    base = adjacent_output_base()
    for root in [Path(__file__).resolve().parent.parent, base, base.parent, Path.cwd().resolve()]:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(root)
    return candidates


def _discover_llm_rows_from_repo() -> list[dict]:
    for repo_root in _repo_root_candidates():
        module_path = repo_root / "scripts" / "solver_discovery.py"
        if not module_path.is_file():
            continue
        try:
            module_name = f"desktop_solver_discovery_{abs(hash(str(module_path)))}"
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            catalog = module.build_catalog(repo_root)
        except Exception:
            continue

        rows: list[dict] = []
        for row in list(catalog.get("variants") or []):
            if not isinstance(row, dict):
                continue
            family = str(row.get("family") or "").strip().lower()
            variant_id = str(row.get("variant_id") or "").strip().lower()
            if family not in SUPPORTED_FAMILIES or not variant_id:
                continue
            rows.append(
                {
                    "variant_id": variant_id,
                    "family": family,
                    "label": str(row.get("label") or variant_id).strip() or variant_id,
                    "role": "variant",
                    "llm_key": str(row.get("llm_key") or "").strip().lower() or None,
                    "llm_label": str(row.get("llm_label") or "").strip() or None,
                    "binary_name": variant_id,
                }
            )
        normalized = _normalize_solver_rows(rows)
        if normalized:
            return normalized
    return []


def _discover_llm_rows_from_binaries() -> list[dict]:
    binaries_dir = resource_root() / "binaries"
    if not binaries_dir.is_dir():
        return []
    rows: list[dict] = []
    for entry in binaries_dir.iterdir():
        if not entry.is_file():
            continue
        binary_name = entry.stem.lower() if entry.suffix.lower() == ".exe" else entry.name.lower()
        match = re.fullmatch(r"(dijkstra|sp_via|vf3|glasgow)_([a-z0-9_]+)", binary_name)
        if not match:
            continue
        family, llm_key = match.group(1), match.group(2)
        if llm_key == "baseline":
            continue
        family_label = FAMILY_LABELS.get(family, family.upper())
        llm_label = _title_llm_token(llm_key)
        rows.append(
            {
                "variant_id": f"{family}_{llm_key}",
                "family": family,
                "label": f"{family_label} {llm_label}",
                "role": "variant",
                "llm_key": llm_key,
                "llm_label": llm_label,
                "binary_name": f"{family}_{llm_key}",
            }
        )
    return _normalize_solver_rows(rows)


def _default_solver_rows() -> list[dict]:
    rows = list(_baseline_solver_rows())
    discovered_llms = _discover_llm_rows_from_repo() or _discover_llm_rows_from_binaries()
    if discovered_llms:
        rows.extend(discovered_llms)
    else:
        rows.extend(_legacy_llm_solver_rows())
    return _normalize_solver_rows(rows)


def _load_solver_rows_from_manifest() -> list[dict] | None:
    manifest_path = resource_root() / "binaries" / "solver_variants.json"
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    rows = payload.get("solvers")
    if not isinstance(rows, list):
        return None
    normalized = _normalize_solver_rows(rows)
    if not normalized:
        return None
    return normalized


def _load_solver_rows() -> list[dict]:
    merged: dict[str, dict] = {}
    for row in _baseline_solver_rows():
        normalized = _normalize_solver_rows([row])
        if normalized:
            merged[normalized[0]["variant_id"]] = normalized[0]

    manifest_rows = _load_solver_rows_from_manifest()
    if manifest_rows:
        for row in manifest_rows:
            merged[row["variant_id"]] = row

    # Auto-discover LLM variants from repo sources first, then bundled binaries.
    discovered_llm_rows = _discover_llm_rows_from_repo() or _discover_llm_rows_from_binaries()
    if discovered_llm_rows:
        for row in discovered_llm_rows:
            merged[row["variant_id"]] = row

    if len(merged) == len(_baseline_solver_rows()):
        for row in _legacy_llm_solver_rows():
            normalized = _normalize_solver_rows([row])
            if normalized:
                merged[normalized[0]["variant_id"]] = normalized[0]

    rows = list(merged.values())
    rows.sort(key=lambda row: (str(row.get("family") or ""), str(row.get("role") or "") != "baseline", str(row.get("label") or "").lower()))
    return rows


def _resolve_binary_for_variant(root: Path, variant_id: str, binary_name: str) -> Path:
    exe_suffix = ".exe" if sys.platform.startswith("win") else ""
    candidates: list[Path] = [root / "binaries" / f"{binary_name}{exe_suffix}"]

    # Source-tree fallback for local development runs without a packaged binaries folder.
    if variant_id == "dijkstra_baseline":
        candidates.extend([root / "baselines" / "dijkstra", root / "baselines" / "dijkstra.exe"])
    elif variant_id == "dijkstra_dial":
        candidates.extend([root / "baselines" / "dial", root / "baselines" / "dial.exe"])
    elif variant_id == "sp_via_baseline":
        candidates.extend([root / "baselines" / "via_dijkstra", root / "baselines" / "via_dijkstra.exe"])
    elif variant_id == "sp_via_dial":
        candidates.extend([root / "baselines" / "via_dial", root / "baselines" / "via_dial.exe"])
    elif variant_id == "vf3_baseline":
        candidates.extend([root / "baselines" / "vf3lib" / "bin" / "vf3", root / "baselines" / "vf3lib" / "bin" / "vf3.exe"])
    elif variant_id == "glasgow_baseline":
        candidates.extend(
            [
                root / "baselines" / "glasgow-subgraph-solver" / "build" / "glasgow_subgraph_solver",
                root / "baselines" / "glasgow-subgraph-solver" / "build" / "glasgow_subgraph_solver.exe",
                root / "baselines" / "glasgow-subgraph-solver" / "build" / "Release" / "glasgow_subgraph_solver",
                root / "baselines" / "glasgow-subgraph-solver" / "build" / "Release" / "glasgow_subgraph_solver.exe",
                root / "baselines" / "glasgow-subgraph-solver" / "build" / "src" / "glasgow_subgraph_solver",
                root / "baselines" / "glasgow-subgraph-solver" / "build" / "src" / "glasgow_subgraph_solver.exe",
                root / "baselines" / "glasgow-subgraph-solver" / "build" / "src" / "Release" / "glasgow_subgraph_solver",
                root / "baselines" / "glasgow-subgraph-solver" / "build" / "src" / "Release" / "glasgow_subgraph_solver.exe",
            ]
        )
    else:
        candidates.extend([root / "src" / binary_name, root / "src" / f"{binary_name}.exe"])
        legacy_aliases = {
            "dijkstra_chatgpt": ["dijkstra_llm"],
            "vf3_chatgpt": ["chatvf3"],
            "vf3_gemini": ["vf3"],
        }
        for alias in legacy_aliases.get(variant_id, []):
            candidates.extend([root / "src" / alias, root / "src" / f"{alias}.exe"])

    seen: set[str] = set()
    deduped: list[Path] = []
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    for path in deduped:
        if path.is_file():
            return path
    return deduped[0]


def _build_solver_variants_and_binary_map() -> tuple[list[SolverVariant], dict[str, Path]]:
    root = resource_root()
    rows = _load_solver_rows()
    variants: list[SolverVariant] = []
    binary_map: dict[str, Path] = {}
    for row in rows:
        variant_id = str(row.get("variant_id") or "").strip()
        family = str(row.get("family") or "").strip().lower()
        if not variant_id or family not in SUPPORTED_FAMILIES:
            continue
        tab_id = "shortest_path" if family in {"dijkstra", "sp_via", "dial"} else "subgraph"
        label = str(row.get("label") or variant_id)
        role = str(row.get("role") or "variant").strip().lower() or "variant"
        variants.append(SolverVariant(variant_id, label, tab_id, family, role))
        binary_name = str(row.get("binary_name") or variant_id).strip() or variant_id
        binary_map[variant_id] = _resolve_binary_for_variant(root, variant_id, binary_name)
    family_order = {"dijkstra": 0, "dial": 1, "sp_via": 2, "vf3": 3, "glasgow": 4}
    variants.sort(
        key=lambda item: (
            item.tab_id,
            family_order.get(item.family, 99),
            item.family,
            item.role != "baseline",
            item.label.lower(),
        )
    )
    return variants, binary_map


SOLVER_VARIANTS, _DEFAULT_BINARY_PATH_MAP = _build_solver_variants_and_binary_map()


def build_binary_path_map() -> dict[str, Path]:
    return dict(_DEFAULT_BINARY_PATH_MAP)


def _prepend_env_path(env: dict[str, str], path_value: Path | str) -> None:
    raw = str(path_value or "").strip()
    if not raw:
        return
    current = str(env.get("PATH") or "")
    parts = [part for part in current.split(os.pathsep) if part]
    if os.name == "nt":
        if any(part.lower() == raw.lower() for part in parts):
            return
    elif raw in parts:
        return
    env["PATH"] = os.pathsep.join([raw, *parts])


def runtime_env_for_binary(binary_path: Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    if not sys.platform.startswith("win"):
        return env
    for candidate in (Path(r"C:\msys64\usr\bin"), Path(r"C:\msys64\mingw64\bin")):
        if candidate.is_dir():
            _prepend_env_path(env, candidate)
    try:
        parent = binary_path.resolve().parent
    except OSError:
        parent = binary_path.parent
    if parent.is_dir():
        _prepend_env_path(env, parent)
    return env


def generate_directed_edges(n: int, rng: random.Random, density: float):
    edges: dict[tuple[int, int], int] = {}
    for i in range(n - 1):
        edges[(i, i + 1)] = rng.randint(1, 20)
    max_edges = n * (n - 1)
    target_edges = max(n - 1, min(max_edges, int(round(density * max_edges))))
    attempts = 0
    while len(edges) < target_edges and attempts < target_edges * 10:
        u = rng.randrange(n)
        v = rng.randrange(n)
        if u == v:
            attempts += 1
            continue
        if u in (0, n - 1) or v in (0, n - 1):
            attempts += 1
            continue
        if (u, v) not in edges:
            edges[(u, v)] = rng.randint(1, 20)
        attempts += 1
    return [(u, v, w) for (u, v), w in edges.items()]


def generate_adjacency(n: int, rng: random.Random, density: float):
    adj = [set() for _ in range(n)]
    for i in range(n - 1):
        adj[i].add(i + 1)
    max_edges = n * (n - 1)
    target_edges = max(n - 1, min(max_edges, int(round(density * max_edges))))
    attempts = 0
    while sum(len(s) for s in adj) < target_edges and attempts < target_edges * 10:
        u = rng.randrange(n)
        v = rng.randrange(n)
        if u == v:
            attempts += 1
            continue
        adj[u].add(v)
        attempts += 1
    return [sorted(list(s)) for s in adj]


def build_undirected_adj(adj):
    undirected = [set(neigh) for neigh in adj]
    for u, neighbors in enumerate(adj):
        for v in neighbors:
            if v < 0 or v >= len(adj) or v == u:
                continue
            undirected[u].add(v)
            undirected[v].add(u)
    return [sorted(list(s)) for s in undirected]


def sanitize_undirected_simple_adj(adj):
    n = len(adj)
    cleaned = [set() for _ in range(n)]
    for u, neighbors in enumerate(adj):
        for raw_v in neighbors:
            try:
                v = int(raw_v)
            except (TypeError, ValueError):
                continue
            if v < 0 or v >= n or v == u:
                continue
            cleaned[u].add(v)
            cleaned[v].add(u)
    return [sorted(list(s)) for s in cleaned]


def pick_connected_nodes(undirected_adj, k: int, rng: random.Random):
    n = len(undirected_adj)
    if k <= 0 or k > n:
        raise ValueError("k must be between 1 and N")
    remaining = set(range(n))
    component = None
    while remaining:
        start = rng.choice(tuple(remaining))
        queue = [start]
        comp = []
        seen = {start}
        while queue:
            u = queue.pop()
            comp.append(u)
            for v in undirected_adj[u]:
                if v not in seen:
                    seen.add(v)
                    queue.append(v)
        remaining.difference_update(seen)
        if len(comp) >= k:
            component = comp
            break
    if component is None:
        raise ValueError("No connected component large enough for k")
    start = rng.choice(component)
    selected = {start}
    frontier = set(undirected_adj[start]) - selected
    while len(selected) < k:
        if not frontier:
            raise ValueError("Failed to build connected pattern")
        nxt = rng.choice(tuple(frontier))
        frontier.discard(nxt)
        if nxt in selected:
            continue
        selected.add(nxt)
        for v in undirected_adj[nxt]:
            if v not in selected:
                frontier.add(v)
    return list(selected)


def write_dijkstra_csv(path: Path, edges, labels):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(f"# start={labels[0]} target={labels[-1]}\n")
        writer = csv.writer(fh)
        writer.writerow(["source", "target", "weight"])
        for u, v, w in edges:
            writer.writerow([labels[u], labels[v], w])


def write_vf(path: Path, adj, labels):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for i, label in enumerate(labels):
            fh.write(f"{i} {label}\n")
        for i, neighbors in enumerate(adj):
            fh.write(f"{len(neighbors)}\n")
            for v in neighbors:
                fh.write(f"{i} {v}\n")


def write_vertex_labelled_lad(path: Path, adj, labels):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for i, neighbors in enumerate(adj):
            line = f"{labels[i]} {len(neighbors)}"
            if neighbors:
                line += " " + " ".join(str(v) for v in neighbors)
            fh.write(line + "\n")


def write_unlabelled_lad(path: Path, adj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for neighbors in adj:
            row = [str(len(neighbors))]
            row.extend(str(int(v)) for v in neighbors)
            fh.write(" ".join(row) + "\n")


def generate_dijkstra_inputs(
    out_dir: Path,
    n: int,
    density: float,
    seed: int,
    graph_family: str = "random_density",
) -> Path:
    rng = random.Random(seed)
    labels = [f"v{i}" for i in range(n)]
    edges = generator_mod.generate_directed_edges(n, rng, density, graph_family=graph_family)
    path = out_dir / "dijkstra_generated.csv"
    write_dijkstra_csv(path, edges, labels)
    max_edges = n * (n - 1)
    metadata = {
        "algorithm": "dijkstra",
        "graph_family": generator_mod.normalize_graph_family(graph_family),
        "n": int(n),
        "k": None,
        "density": float(density),
        "actual_density": 0.0 if max_edges <= 0 else float(len(edges)) / float(max_edges),
        "seed": int(seed),
        "files": [path.as_posix()],
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return path


def generate_subgraph_inputs(
    out_dir: Path,
    n: int,
    k: int,
    density: float,
    seed: int,
    graph_family: str = "random_density",
):
    if k >= n:
        raise ValueError("k must be smaller than N")
    rng = random.Random(seed)
    target_adj = generator_mod.generate_adjacency(n, rng, density, graph_family=graph_family)
    undirected = sanitize_undirected_simple_adj(build_undirected_adj(target_adj))
    nodes = pick_connected_nodes(undirected, k, rng)
    labels = [i % 4 for i in range(n)]
    node_set = set(nodes)
    pattern_map = {node: idx for idx, node in enumerate(nodes)}
    pattern_adj = []
    for node in nodes:
        neighbors = [pattern_map[v] for v in undirected[node] if v in node_set]
        pattern_adj.append(sorted(neighbors))
    pattern_adj = sanitize_undirected_simple_adj(pattern_adj)
    pattern_labels = [labels[node] for node in nodes]

    vf_target = out_dir / "vf3_target.vf"
    vf_pattern = out_dir / "vf3_pattern.vf"
    lad_target = out_dir / "glasgow_target.lad"
    lad_pattern = out_dir / "glasgow_pattern.lad"

    write_vf(vf_target, undirected, labels)
    write_vf(vf_pattern, pattern_adj, pattern_labels)
    write_vertex_labelled_lad(lad_target, undirected, labels)
    write_vertex_labelled_lad(lad_pattern, pattern_adj, pattern_labels)
    actual_edges = count_adj_edges(undirected) // 2
    max_edges = (n * (n - 1)) // 2
    metadata = {
        "algorithm": "subgraph",
        "graph_family": generator_mod.normalize_graph_family(graph_family),
        "n": int(n),
        "k": int(k),
        "density": float(density),
        "actual_density": 0.0 if max_edges <= 0 else float(actual_edges) / float(max_edges),
        "seed": int(seed),
        "pattern_nodes": [int(node) for node in nodes],
        "files": [
            lad_pattern.as_posix(),
            lad_target.as_posix(),
            vf_pattern.as_posix(),
            vf_target.as_posix(),
        ],
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {
        "vf_pattern": vf_pattern,
        "vf_target": vf_target,
        "lad_pattern": lad_pattern,
        "lad_target": lad_target,
        "lad_format": "vertexlabelledlad",
    }


def write_dijkstra_csv_with_labels(path: Path, edges: list[tuple[str, str, int]], start_label: str, target_label: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(f"# start={start_label} target={target_label}\n")
        writer = csv.writer(fh)
        writer.writerow(["source", "target", "weight"])
        for src, dst, weight in edges:
            writer.writerow([str(src), str(dst), int(weight)])


def normalize_adj_lists(adj: list[list[int]]) -> list[list[int]]:
    n = len(adj)
    normalized: list[list[int]] = []
    for u, neighbors in enumerate(adj):
        row = sorted({int(v) for v in neighbors if 0 <= int(v) < n and int(v) != u})
        normalized.append(row)
    return normalized


def count_adj_edges(adj: list[list[int]]) -> int:
    return int(sum(len(row) for row in adj))


def dataset_storage_root() -> Path:
    override = str(os.environ.get("CAPSTONE_DATASETS_DIR") or "").strip()
    if override:
        root = Path(override).expanduser()
    elif sys.platform.startswith("win"):
        local_appdata = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if local_appdata:
            root = Path(local_appdata) / "CapstoneBenchmarkRunner" / "datasets"
        else:
            root = Path.home() / "AppData" / "Local" / "CapstoneBenchmarkRunner" / "datasets"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "CapstoneBenchmarkRunner" / "datasets"
    else:
        xdg_data_home = str(os.environ.get("XDG_DATA_HOME") or "").strip()
        if xdg_data_home:
            root = Path(xdg_data_home) / "capstone-benchmark-runner" / "datasets"
        else:
            root = Path.home() / ".local" / "share" / "capstone-benchmark-runner" / "datasets"
    try:
        root.mkdir(parents=True, exist_ok=True)
        return root
    except OSError:
        # Last-resort fallback keeps behavior working even in restricted environments.
        fallback = adjacent_output_base() / ".datasets"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def dataset_dir_for_spec(spec: DatasetSpec) -> Path:
    return dataset_storage_root() / spec.tab_id / spec.dataset_id


def _dir_total_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += int(child.stat().st_size)
        except OSError:
            continue
    return total


def _count_graph_files(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    valid_suffixes = {".vf", ".grf", ".lad", ".csv"}
    for child in path.rglob("*"):
        try:
            if child.is_file() and child.suffix.lower() in valid_suffixes:
                count += 1
        except OSError:
            continue
    return count


def _dataset_meta_path(dataset_dir: Path) -> Path:
    return dataset_dir / "dataset_meta.json"


def read_dataset_meta(dataset_dir: Path) -> dict:
    path = _dataset_meta_path(dataset_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_dataset_meta(dataset_dir: Path, payload: dict):
    dataset_dir.mkdir(parents=True, exist_ok=True)
    _dataset_meta_path(dataset_dir).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def dataset_raw_ready(spec: DatasetSpec) -> bool:
    dataset_dir = dataset_dir_for_spec(spec)
    meta = read_dataset_meta(dataset_dir)
    return bool(meta.get("raw_ready", False))


def dataset_converted_ready(spec: DatasetSpec) -> bool:
    dataset_dir = dataset_dir_for_spec(spec)
    meta = read_dataset_meta(dataset_dir)
    return bool(meta.get("converted_ready", False))


def dataset_converted_inputs(spec: DatasetSpec) -> dict[str, Path | str] | None:
    dataset_dir = dataset_dir_for_spec(spec)
    meta = read_dataset_meta(dataset_dir)
    raw_inputs = meta.get("inputs")
    if not isinstance(raw_inputs, dict):
        return None
    resolved: dict[str, Path | str] = {}
    for key, raw_path in raw_inputs.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        if str(key) == "lad_format":
            resolved[str(key)] = str(raw_path).strip()
            continue
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = dataset_dir / raw_path
        if candidate.exists():
            resolved[str(key)] = candidate
    return resolved or None


def _dataset_download_kind(spec: DatasetSpec) -> str:
    download = dict(spec.download or {})
    return str(download.get("kind") or "").strip().lower()


def _raw_dataset_has_files(dataset_dir: Path) -> bool:
    raw_dir = dataset_dir / "raw"
    if not raw_dir.exists():
        return False
    for child in raw_dir.rglob("*"):
        try:
            if child.is_file():
                return True
        except OSError:
            continue
    return False


def _http_download_with_resume(url: str, destination: Path, *, retries: int = 8, timeout_seconds: float = 60.0):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.is_file():
        return
    temp_path = destination.with_suffix(destination.suffix + ".part")
    backoff_seconds = 1.0
    for attempt in range(retries):
        existing = int(temp_path.stat().st_size) if temp_path.exists() else 0
        headers = {"User-Agent": "capstone-benchmark-runner/1.0"}
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status_code = int(getattr(response, "status", response.getcode()))
                mode = "ab"
                if existing > 0 and status_code != 206:
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                    existing = 0
                    mode = "wb"
                elif existing == 0:
                    mode = "wb"
                with temp_path.open(mode) as out_fh:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out_fh.write(chunk)
            temp_path.replace(destination)
            return
        except Exception:
            if attempt >= retries - 1:
                raise
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2.0, 12.0)


def _download_dataset_raw_files(spec: DatasetSpec, dataset_dir: Path):
    download = dict(spec.download or {})
    kind = str(download.get("kind") or "").strip().lower()
    if kind == "manual_request":
        return
    if kind == "single_file":
        url = str(download.get("url") or "").strip()
        rel = str(download.get("relative_path") or "").strip()
        if not url or not rel:
            raise RuntimeError(f"Invalid single_file download configuration for {spec.dataset_id}.")
        _http_download_with_resume(url, dataset_dir / rel)
        return
    if kind == "multi_file":
        files = list(download.get("files") or [])
        if not files:
            raise RuntimeError(f"Invalid multi_file download configuration for {spec.dataset_id}.")
        for item in files:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            rel = str(item.get("relative_path") or "").strip()
            if not url or not rel:
                continue
            _http_download_with_resume(url, dataset_dir / rel)
        return
    raise RuntimeError(f"Unsupported download kind '{kind}' for {spec.dataset_id}.")


def _extract_member_from_tgz(archive_path: Path, member_name: str, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tf:
        try:
            member = tf.getmember(member_name)
        except KeyError as exc:
            raise RuntimeError(f"Archive member missing: {member_name}") from exc
        if not member.isfile():
            raise RuntimeError(f"Archive member is not a regular file: {member_name}")
        extracted = tf.extractfile(member)
        if extracted is None:
            raise RuntimeError(f"Failed to extract archive member: {member_name}")
        data = extracted.read()
    destination.write_bytes(data)


def _encode_label_tokens(pattern_tokens: list[str], target_tokens: list[str]) -> tuple[list[int], list[int]]:
    lookup: dict[str, int] = {}

    def _encode(items: list[str]) -> list[int]:
        encoded: list[int] = []
        for item in items:
            token = str(item or "__node__").strip() or "__node__"
            if token not in lookup:
                lookup[token] = len(lookup)
            encoded.append(int(lookup[token]))
        return encoded

    return _encode(pattern_tokens), _encode(target_tokens)


def _decode_text_lines(blob: bytes) -> list[str]:
    text = blob.decode("utf-8", errors="replace")
    return [line.strip() for line in text.replace("\r", "").split("\n") if line.strip()]


def _parse_mivia_graph_bytes(data: bytes, labeled: bool) -> tuple[list[list[int]], list[str] | None]:
    if len(data) < 2:
        raise RuntimeError("MIVIA graph payload is too small.")
    words = [int.from_bytes(data[idx : idx + 2], "little", signed=False) for idx in range(0, len(data) - 1, 2)]
    if not words:
        raise RuntimeError("MIVIA graph payload is empty.")
    n = int(words[0])
    if n <= 0:
        raise RuntimeError("MIVIA graph has an invalid node count.")
    cursor = 1
    labels: list[str] | None = None
    if labeled:
        if len(words) < 1 + n:
            raise RuntimeError("Labeled MIVIA graph payload is truncated.")
        labels = [f"label_{int(words[cursor + idx])}" for idx in range(n)]
        cursor += n
    adj: list[list[int]] = []
    for _node in range(n):
        if cursor >= len(words):
            raise RuntimeError("MIVIA graph payload ended before adjacency rows were complete.")
        degree = int(words[cursor])
        cursor += 1
        row: list[int] = []
        for _edge in range(max(0, degree)):
            if cursor >= len(words):
                raise RuntimeError("MIVIA graph payload ended during an adjacency row.")
            dst = int(words[cursor])
            cursor += 1
            row.append(dst)
            if labeled:
                if cursor >= len(words):
                    raise RuntimeError("Labeled MIVIA graph payload ended during edge attributes.")
                cursor += 1
        adj.append(row)
    return normalize_adj_lists(adj), labels


def _select_mivia_pair(archive_path: Path, prepare: dict) -> tuple[list[list[int]], list[list[int]], list[str] | None, list[str] | None, dict]:
    desired_prefix = str(prepare.get("inner_zip_prefix") or "si2_").strip().lower()
    labeled = bool(prepare.get("labeled", False))
    with zipfile.ZipFile(archive_path) as outer_zip:
        names = outer_zip.namelist()
        inner_candidates = sorted(name for name in names if name.lower().endswith(".zip"))
        if not inner_candidates:
            raise RuntimeError("MIVIA outer archive does not contain any inner ZIP members.")
        inner_name = next((name for name in inner_candidates if Path(name).name.lower().startswith(desired_prefix)), inner_candidates[0])
        stem = Path(inner_name).stem.lower()
        gtr_name = next(
            (
                name
                for name in names
                if name.lower().endswith(".gtr") and Path(name).stem.lower() == stem
            ),
            None,
        )
        if gtr_name is None:
            raise RuntimeError(f"No .gtr file found for MIVIA archive member: {inner_name}")
        gtr_lines = _decode_text_lines(outer_zip.read(gtr_name))
        if not gtr_lines:
            raise RuntimeError(f"MIVIA .gtr file is empty: {gtr_name}")
        graph_a_name = str(gtr_lines[0].split()[0]).strip()
        if ".a" not in graph_a_name.lower():
            raise RuntimeError(f"Unexpected MIVIA pair token in {gtr_name}: {graph_a_name}")
        graph_b_name = re.sub(r"\.A", ".B", graph_a_name, count=1, flags=re.IGNORECASE)
        inner_data = outer_zip.read(inner_name)
    with zipfile.ZipFile(io.BytesIO(inner_data)) as inner_zip:
        inner_names = inner_zip.namelist()
        member_a = next((name for name in inner_names if Path(name).name == graph_a_name), None)
        member_b = next((name for name in inner_names if Path(name).name == graph_b_name), None)
        if member_a is None or member_b is None:
            raise RuntimeError(f"Could not resolve MIVIA pair members for {graph_a_name} / {graph_b_name}")
        pattern_adj, pattern_labels = _parse_mivia_graph_bytes(inner_zip.read(member_a), labeled=labeled)
        target_adj, target_labels = _parse_mivia_graph_bytes(inner_zip.read(member_b), labeled=labeled)
    return pattern_adj, target_adj, pattern_labels, target_labels, {
        "selected_archive": Path(inner_name).name,
        "selected_pair": f"{graph_a_name}|{graph_b_name}",
    }


def _parse_bigraph_control_labels(header_line: str) -> list[str]:
    labels: list[str] = []
    for match in re.finditer(r"\((\d+),\s*([^:]+):\s*\d+\)", header_line):
        idx = int(match.group(1))
        token = str(match.group(2)).strip() or "__node__"
        while len(labels) <= idx:
            labels.append("__node__")
        labels[idx] = token
    return labels


def _parse_bigraph_instance(text: str) -> tuple[list[list[int]], list[str]]:
    lines = [line.strip() for line in str(text or "").replace("\r", "").split("\n") if line.strip()]
    if len(lines) < 2:
        raise RuntimeError("Bigraph instance is too short.")
    node_labels = _parse_bigraph_control_labels(lines[0])
    header_values = parse_int_tokens(lines[1])
    if len(header_values) < 3:
        raise RuntimeError("Bigraph header is missing root/node/site counts.")
    root_count = int(header_values[0])
    node_count = int(header_values[1])
    site_count = int(header_values[2])
    if node_count <= 0:
        raise RuntimeError("Bigraph instance has no nodes.")
    while len(node_labels) < node_count:
        node_labels.append("__node__")
    matrix_rows = root_count + node_count
    matrix_cols = node_count + site_count
    adj: list[set[int]] = [set() for _ in range(root_count + node_count + site_count)]
    cursor = 2
    parsed_rows = 0
    while cursor < len(lines) and parsed_rows < matrix_rows:
        bits = "".join(ch for ch in lines[cursor] if ch in {"0", "1"})
        cursor += 1
        if not bits:
            continue
        row = bits[:matrix_cols].ljust(matrix_cols, "0")
        parent_idx = parsed_rows
        parent_vertex = parent_idx if parent_idx < root_count else root_count + (parent_idx - root_count)
        for col_idx, bit in enumerate(row):
            if bit != "1":
                continue
            child_vertex = root_count + col_idx if col_idx < node_count else root_count + node_count + (col_idx - node_count)
            if child_vertex != parent_vertex:
                adj[parent_vertex].add(child_vertex)
                adj[child_vertex].add(parent_vertex)
        parsed_rows += 1
    label_tokens = (["__root__"] * root_count) + node_labels[:node_count] + (["__site__"] * site_count)
    for line in lines[cursor:]:
        node_ids = sorted({int(match.group(1)) for match in re.finditer(r"\((\d+),\s*\d+\)", line) if int(match.group(1)) < node_count})
        if not node_ids:
            continue
        handle_idx = len(adj)
        adj.append(set())
        label_tokens.append("__handle__")
        for node_id in node_ids:
            node_vertex = root_count + node_id
            adj[handle_idx].add(node_vertex)
            adj[node_vertex].add(handle_idx)
    return normalize_adj_lists([sorted(row) for row in adj]), label_tokens


def _select_bigraph_pair(archive_path: Path, prepare: dict) -> tuple[list[list[int]], list[list[int]], list[str], list[str], dict]:
    list_member = str(prepare.get("instances_member") or "instances/savannah_instances.txt").strip()
    with tarfile.open(archive_path, "r:xz") as tf:
        try:
            listing_member = tf.getmember(list_member)
        except KeyError as exc:
            raise RuntimeError(f"Bigraph instance listing missing: {list_member}") from exc
        listing_fh = tf.extractfile(listing_member)
        if listing_fh is None:
            raise RuntimeError(f"Failed to extract bigraph instance listing: {list_member}")
        listing_lines = _decode_text_lines(listing_fh.read())
        if not listing_lines:
            raise RuntimeError(f"Bigraph instance listing is empty: {list_member}")
        instance_id, pattern_member, target_member = listing_lines[0].split()[:3]
        pattern_fh = tf.extractfile(pattern_member)
        target_fh = tf.extractfile(target_member)
        if pattern_fh is None or target_fh is None:
            raise RuntimeError(f"Failed to extract bigraph pair members: {pattern_member} / {target_member}")
        pattern_adj, pattern_labels = _parse_bigraph_instance(pattern_fh.read().decode("utf-8", errors="replace"))
        target_adj, target_labels = _parse_bigraph_instance(target_fh.read().decode("utf-8", errors="replace"))
    return pattern_adj, target_adj, pattern_labels, target_labels, {
        "selected_instance": instance_id,
        "selected_pair": f"{pattern_member}|{target_member}",
    }


def _convert_subgraph_from_adj_pair(
    dataset_dir: Path,
    pattern_adj: list[list[int]],
    target_adj: list[list[int]],
    source_kind: str,
    pattern_labels: list[str] | None = None,
    target_labels: list[str] | None = None,
    extra_meta: dict | None = None,
) -> dict:
    pattern_adj = normalize_adj_lists(pattern_adj)
    target_adj = normalize_adj_lists(target_adj)
    converted_dir = dataset_dir / "converted"
    converted_dir.mkdir(parents=True, exist_ok=True)

    vf_pattern = converted_dir / "vf3_pattern.vf"
    vf_target = converted_dir / "vf3_target.vf"
    lad_pattern = converted_dir / "glasgow_pattern.lad"
    lad_target = converted_dir / "glasgow_target.lad"

    lad_format = "lad"
    if pattern_labels is not None or target_labels is not None:
        if pattern_labels is None:
            pattern_labels = ["__node__"] * len(pattern_adj)
        if target_labels is None:
            target_labels = ["__node__"] * len(target_adj)
        if len(pattern_labels) != len(pattern_adj) or len(target_labels) != len(target_adj):
            raise RuntimeError("Subgraph conversion label counts do not match adjacency sizes.")
        encoded_pattern_labels, encoded_target_labels = _encode_label_tokens(pattern_labels, target_labels)
        write_vf(vf_pattern, pattern_adj, encoded_pattern_labels)
        write_vf(vf_target, target_adj, encoded_target_labels)
        write_vertex_labelled_lad(lad_pattern, pattern_adj, encoded_pattern_labels)
        write_vertex_labelled_lad(lad_target, target_adj, encoded_target_labels)
        lad_format = "vertexlabelledlad"
    else:
        write_vf(vf_pattern, pattern_adj, [0] * len(pattern_adj))
        write_vf(vf_target, target_adj, [0] * len(target_adj))
        write_unlabelled_lad(lad_pattern, pattern_adj)
        write_unlabelled_lad(lad_target, target_adj)

    parsed_vf_pattern = normalize_adj_lists(parse_vf_graph(vf_pattern))
    parsed_vf_target = normalize_adj_lists(parse_vf_graph(vf_target))
    parsed_lad_pattern = normalize_adj_lists(parse_lad_graph(lad_pattern))
    parsed_lad_target = normalize_adj_lists(parse_lad_graph(lad_target))

    if parsed_vf_pattern != pattern_adj or parsed_lad_pattern != pattern_adj:
        raise RuntimeError("Converted pattern graph failed identity verification across VF/LAD.")
    if parsed_vf_target != target_adj or parsed_lad_target != target_adj:
        raise RuntimeError("Converted target graph failed identity verification across VF/LAD.")

    return {
        "raw_ready": True,
        "converted_ready": True,
        "source_kind": source_kind,
        "inputs": {
            "vf_pattern": str(vf_pattern),
            "vf_target": str(vf_target),
            "lad_pattern": str(lad_pattern),
            "lad_target": str(lad_target),
            "lad_format": lad_format,
        },
        "graph_file_count": 2,
        "pair_count": 1,
        "pattern_nodes": len(pattern_adj),
        "target_nodes": len(target_adj),
        "pattern_edges": count_adj_edges(pattern_adj),
        "target_edges": count_adj_edges(target_adj),
        **(dict(extra_meta or {})),
    }


def _convert_shortest_path_from_edge_list(
    dataset_dir: Path,
    source_path: Path,
    assume_undirected: bool,
) -> dict:
    converted_dir = dataset_dir / "converted"
    converted_dir.mkdir(parents=True, exist_ok=True)
    dijkstra_csv = converted_dir / "dijkstra_input.csv"
    temp_edges = converted_dir / "edge_rows.tmp.csv"

    opener = gzip.open if source_path.suffix.lower() == ".gz" else open
    announced_nodes = 0
    nodes_seen: set[str] | None = set()
    first_seen: str | None = None
    second_seen: str | None = None
    last_seen: str | None = None
    numeric_min: int | None = None
    numeric_max: int | None = None
    edge_count = 0

    with opener(source_path, "rt", encoding="utf-8", errors="replace") as in_fh, temp_edges.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as out_fh:
        for raw_line in in_fh:
            line = str(raw_line or "").strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith("%"):
                if announced_nodes <= 0:
                    node_match = re.search(r"Nodes:\s*(\d+)", line, flags=re.IGNORECASE)
                    if node_match:
                        announced_nodes = max(announced_nodes, int(node_match.group(1)))
                continue
            parts = re.split(r"[\s,;]+", line)
            if len(parts) < 2:
                continue
            u = parts[0].strip()
            v = parts[1].strip()
            if not u or not v or u == v:
                continue

            if first_seen is None:
                first_seen = u
                second_seen = v
            last_seen = v

            if nodes_seen is not None:
                nodes_seen.add(u)
                nodes_seen.add(v)
                if len(nodes_seen) > 1_000_000:
                    nodes_seen = None

            try:
                ui = int(u)
                vi = int(v)
            except ValueError:
                pass
            else:
                low = ui if ui <= vi else vi
                high = vi if vi >= ui else ui
                numeric_min = low if numeric_min is None else min(numeric_min, low)
                numeric_max = high if numeric_max is None else max(numeric_max, high)

            out_fh.write(f"{u},{v},1\n")
            edge_count += 1
            if assume_undirected:
                out_fh.write(f"{v},{u},1\n")
                edge_count += 1

    if edge_count <= 0:
        try:
            temp_edges.unlink()
        except OSError:
            pass
        raise RuntimeError(f"No parseable edges found in {source_path}.")

    if announced_nodes > 0:
        n_nodes = announced_nodes
    elif nodes_seen is not None:
        n_nodes = len(nodes_seen)
    elif numeric_min is not None and numeric_max is not None and numeric_max >= numeric_min:
        n_nodes = int((numeric_max - numeric_min) + 1)
    else:
        n_nodes = 0
    if n_nodes < 2:
        try:
            temp_edges.unlink()
        except OSError:
            pass
        raise RuntimeError("Converted shortest-path dataset has fewer than 2 nodes.")

    if numeric_min is not None and numeric_max is not None and numeric_max > numeric_min:
        start_label = str(numeric_min)
        target_label = str(numeric_max)
    else:
        start_label = str(first_seen or "")
        target_label = str(last_seen or second_seen or "")
    if not start_label or not target_label or start_label == target_label:
        if nodes_seen is not None and len(nodes_seen) >= 2:
            ordered_nodes = sorted(nodes_seen)
            start_label = ordered_nodes[0]
            target_label = ordered_nodes[-1]
    if not start_label or not target_label or start_label == target_label:
        try:
            temp_edges.unlink()
        except OSError:
            pass
        raise RuntimeError("Could not derive distinct start/target node labels for shortest-path conversion.")

    with dijkstra_csv.open("w", encoding="utf-8", newline="") as out_fh:
        out_fh.write(f"# start={start_label} target={target_label}\n")
        out_fh.write("source,target,weight\n")
        with temp_edges.open("r", encoding="utf-8", errors="replace") as in_fh:
            shutil.copyfileobj(in_fh, out_fh, length=1024 * 1024)
    try:
        temp_edges.unlink()
    except OSError:
        pass

    density = 0.0
    if n_nodes > 1:
        density = min(1.0, float(edge_count) / float(n_nodes * (n_nodes - 1)))

    return {
        "raw_ready": True,
        "converted_ready": True,
        "source_kind": "edge_list",
        "inputs": {
            "dijkstra_file": str(dijkstra_csv),
        },
        "graph_file_count": 1,
        "pair_count": 1,
        "nodes": n_nodes,
        "edges": int(edge_count),
        "density": float(density),
        "start_label": start_label,
        "target_label": target_label,
    }


def _convert_shortest_path_from_dimacs_gr(
    dataset_dir: Path,
    source_path: Path,
) -> dict:
    converted_dir = dataset_dir / "converted"
    converted_dir.mkdir(parents=True, exist_ok=True)
    dijkstra_csv = converted_dir / "dijkstra_input.csv"
    temp_edges = converted_dir / "edge_rows.tmp.csv"

    opener = gzip.open if source_path.suffix.lower() == ".gz" else open
    declared_nodes = 0
    min_node_id: int | None = None
    max_node_id: int | None = None
    edge_count = 0
    with opener(source_path, "rt", encoding="utf-8", errors="replace") as in_fh, temp_edges.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as out_fh:
        for raw_line in in_fh:
            line = str(raw_line or "").strip()
            if not line:
                continue
            token = line[0].lower()
            if token == "c":
                continue
            if token == "p":
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        declared_nodes = int(parts[2])
                    except ValueError:
                        declared_nodes = 0
                continue
            if token != "a":
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                src = int(parts[1])
                dst = int(parts[2])
                weight = int(float(parts[3]))
            except ValueError:
                continue
            if src == dst:
                continue
            out_fh.write(f"{src},{dst},{weight}\n")
            edge_count += 1
            low = src if src <= dst else dst
            high = dst if dst >= src else src
            min_node_id = low if min_node_id is None else min(min_node_id, low)
            max_node_id = high if max_node_id is None else max(max_node_id, high)

    if edge_count <= 0:
        try:
            temp_edges.unlink()
        except OSError:
            pass
        raise RuntimeError(f"No parseable arc rows found in DIMACS source {source_path}.")

    if declared_nodes > 0:
        n_nodes = declared_nodes
        start_label = "1"
        target_label = str(declared_nodes)
    elif min_node_id is not None and max_node_id is not None and max_node_id >= min_node_id:
        n_nodes = int((max_node_id - min_node_id) + 1)
        start_label = str(min_node_id)
        target_label = str(max_node_id)
    else:
        try:
            temp_edges.unlink()
        except OSError:
            pass
        raise RuntimeError("Could not derive node range for DIMACS conversion.")
    if n_nodes < 2 or start_label == target_label:
        try:
            temp_edges.unlink()
        except OSError:
            pass
        raise RuntimeError("DIMACS conversion produced an invalid node range.")

    with dijkstra_csv.open("w", encoding="utf-8", newline="") as out_fh:
        out_fh.write(f"# start={start_label} target={target_label}\n")
        out_fh.write("source,target,weight\n")
        with temp_edges.open("r", encoding="utf-8", errors="replace") as in_fh:
            shutil.copyfileobj(in_fh, out_fh, length=1024 * 1024)
    try:
        temp_edges.unlink()
    except OSError:
        pass

    density = 0.0
    if n_nodes > 1:
        density = min(1.0, float(edge_count) / float(n_nodes * (n_nodes - 1)))

    return {
        "raw_ready": True,
        "converted_ready": True,
        "source_kind": "dimacs_gr",
        "inputs": {
            "dijkstra_file": str(dijkstra_csv),
        },
        "graph_file_count": 1,
        "pair_count": 1,
        "nodes": int(n_nodes),
        "edges": int(edge_count),
        "density": float(density),
        "start_label": start_label,
        "target_label": target_label,
    }


def prepare_dataset(spec: DatasetSpec) -> dict:
    dataset_dir = dataset_dir_for_spec(spec)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    download_kind = _dataset_download_kind(spec)
    _download_dataset_raw_files(spec, dataset_dir)
    raw_payload = read_dataset_meta(dataset_dir)
    raw_ready = True if download_kind != "manual_request" else _raw_dataset_has_files(dataset_dir)
    raw_payload.update(
        {
            "dataset_id": spec.dataset_id,
            "name": spec.name,
            "tab_id": spec.tab_id,
            "source": spec.source,
            "source_url": spec.source_url,
            "raw_format": spec.raw_format,
            "description": spec.description,
            "raw_ready": bool(raw_ready),
            "converted_ready": False,
            "storage_size_bytes": int(_dir_total_size_bytes(dataset_dir)),
            "graph_file_count": int(max(0, int(raw_payload.get("graph_file_count") or spec.estimated_graph_files or 0))),
            "pair_count": int(max(0, int(raw_payload.get("pair_count") or spec.estimated_pair_count or 0))),
        }
    )
    write_dataset_meta(dataset_dir, raw_payload)

    prepare = dict(spec.prepare or {})
    kind = str(prepare.get("kind") or "").strip().lower()
    meta_core: dict

    if kind == "subgraph_pair_from_grf_files":
        pat_rel = str(prepare.get("pattern_relative_path") or "").strip()
        tgt_rel = str(prepare.get("target_relative_path") or "").strip()
        if not pat_rel or not tgt_rel:
            raise RuntimeError(f"Missing grf pair paths for {spec.dataset_id}.")
        pat = dataset_dir / pat_rel
        tgt = dataset_dir / tgt_rel
        meta_core = _convert_subgraph_from_adj_pair(
            dataset_dir,
            parse_vf_graph(pat),
            parse_vf_graph(tgt),
            source_kind="grf_pair",
        )
    elif kind == "subgraph_pair_from_tgz_members":
        arc_rel = str(prepare.get("archive_relative_path") or "").strip()
        member_pat = str(prepare.get("pattern_member") or "").strip()
        member_tgt = str(prepare.get("target_member") or "").strip()
        if not arc_rel or not member_pat or not member_tgt:
            raise RuntimeError(f"Missing archive extraction config for {spec.dataset_id}.")
        archive_path = dataset_dir / arc_rel
        extracted_dir = dataset_dir / "extracted"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        pat = extracted_dir / "pattern.lad"
        tgt = extracted_dir / "target.lad"
        _extract_member_from_tgz(archive_path, member_pat, pat)
        _extract_member_from_tgz(archive_path, member_tgt, tgt)
        meta_core = _convert_subgraph_from_adj_pair(
            dataset_dir,
            parse_lad_graph(pat),
            parse_lad_graph(tgt),
            source_kind="lad_pair_from_archive",
        )
    elif kind == "subgraph_pair_from_mivia_archive":
        arc_rel = str(prepare.get("archive_relative_path") or "").strip()
        if not arc_rel:
            raise RuntimeError(f"Missing MIVIA archive path for {spec.dataset_id}.")
        pattern_adj, target_adj, pattern_labels, target_labels, extra_meta = _select_mivia_pair(dataset_dir / arc_rel, prepare)
        meta_core = _convert_subgraph_from_adj_pair(
            dataset_dir,
            pattern_adj,
            target_adj,
            source_kind="mivia_archive_pair",
            pattern_labels=pattern_labels,
            target_labels=target_labels,
            extra_meta=extra_meta,
        )
    elif kind == "subgraph_pair_from_bigraph_archive":
        arc_rel = str(prepare.get("archive_relative_path") or "").strip()
        if not arc_rel:
            raise RuntimeError(f"Missing bigraph archive path for {spec.dataset_id}.")
        pattern_adj, target_adj, pattern_labels, target_labels, extra_meta = _select_bigraph_pair(dataset_dir / arc_rel, prepare)
        meta_core = _convert_subgraph_from_adj_pair(
            dataset_dir,
            pattern_adj,
            target_adj,
            source_kind="bigraph_archive_pair",
            pattern_labels=pattern_labels,
            target_labels=target_labels,
            extra_meta=extra_meta,
        )
    elif kind == "shortest_path_csv_from_edge_list_gz":
        src_rel = str(prepare.get("source_relative_path") or "").strip()
        if not src_rel:
            raise RuntimeError(f"Missing shortest-path source path for {spec.dataset_id}.")
        assume_undirected = bool(prepare.get("assume_undirected", True))
        meta_core = _convert_shortest_path_from_edge_list(dataset_dir, dataset_dir / src_rel, assume_undirected=assume_undirected)
    elif kind == "shortest_path_csv_from_dimacs_gr_gz":
        src_rel = str(prepare.get("source_relative_path") or "").strip()
        if not src_rel:
            raise RuntimeError(f"Missing DIMACS source path for {spec.dataset_id}.")
        meta_core = _convert_shortest_path_from_dimacs_gr(dataset_dir, dataset_dir / src_rel)
    elif kind == "download_only":
        meta_core = {
            "raw_ready": bool(raw_ready),
            "converted_ready": False,
            "source_kind": "download_only",
            "inputs": {},
            "graph_file_count": int(max(0, int(raw_payload.get("graph_file_count") or spec.estimated_graph_files or 0))),
            "pair_count": int(max(0, int(raw_payload.get("pair_count") or spec.estimated_pair_count or 0))),
            "note": str(prepare.get("note") or "Dataset retained as raw-only archive.").strip(),
        }
    elif kind == "manual_request":
        request_url = str(dict(spec.download or {}).get("request_url") or spec.source_url or "").strip()
        meta_core = {
            "raw_ready": bool(raw_ready),
            "converted_ready": False,
            "source_kind": "manual_request",
            "inputs": {},
            "graph_file_count": int(max(0, int(raw_payload.get("graph_file_count") or spec.estimated_graph_files or 0))),
            "pair_count": int(max(0, int(raw_payload.get("pair_count") or spec.estimated_pair_count or 0))),
            "request_url": request_url,
            "note": str(prepare.get("note") or "Dataset requires manual request/import.").strip(),
        }
    else:
        raise RuntimeError(f"Unsupported dataset prepare kind '{kind}' for {spec.dataset_id}.")

    dataset_size = _dir_total_size_bytes(dataset_dir)
    graph_file_count = int(meta_core.get("graph_file_count") or _count_graph_files(dataset_dir / "converted"))
    pair_count = int(meta_core.get("pair_count") or 0)

    payload = {
        "dataset_id": spec.dataset_id,
        "name": spec.name,
        "tab_id": spec.tab_id,
        "source": spec.source,
        "source_url": spec.source_url,
        "raw_format": spec.raw_format,
        "description": spec.description,
        "storage_size_bytes": int(dataset_size),
        "graph_file_count": int(max(0, graph_file_count)),
        "pair_count": int(max(0, pair_count)),
        **meta_core,
    }
    write_dataset_meta(dataset_dir, payload)
    return payload


class BenchmarkRunnerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}")
        self.minsize(1200, 840)
        self.style = ttk.Style(self)
        self.current_theme_mode = self._detect_system_theme_mode()
        self.current_theme_palette = THEME_PALETTES.get(self.current_theme_mode, THEME_PALETTES["light"])
        self.theme_toggle_label_var = tk.StringVar(value="")
        self.theme_toggle_btn: ttk.Button | None = None

        self.binary_paths = build_binary_path_map()
        self.dataset_specs = load_dataset_catalog()
        self.dataset_spec_by_id = {spec.dataset_id: spec for spec in self.dataset_specs}
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.active_proc_lock = threading.Lock()
        self.active_procs: set[subprocess.Popen] = set()
        self.suspended_proc_pids: set[int] = set()
        self.session_output_dir: Path | None = None
        self.last_run_payload: dict | None = None
        self.last_plot_context: dict | None = None
        self.last_runtime_fig: Figure | None = None
        self.last_memory_fig: Figure | None = None
        self.last_runtime_3d_fig: Figure | None = None
        self.last_memory_3d_fig: Figure | None = None
        self.stats_tree: ttk.Treeview | None = None
        self.stats_blurb_label: ttk.Label | None = None
        self.stats_summary_label: ttk.Label | None = None
        self.stats_wrap: ttk.Frame | None = None
        self.stats_sort_column_combo: ttk.Combobox | None = None
        self.stats_sort_note_label: ttk.Label | None = None
        self.run_timer_deadline_monotonic: float | None = None
        self.run_timer_after_id: str | None = None
        self.live_log_lines: dict[str, str] = {}
        self.drilldown_popup: tk.Toplevel | None = None
        self.drilldown_popup_mode: str | None = None
        self.drilldown_popup_point_key: tuple | None = None
        self.drilldown_highlight_artist = None
        self.drilldown_highlight_canvas: FigureCanvasTkAgg | None = None
        self.stats_help_popup: tk.Toplevel | None = None
        self.visualizer_embed_enabled = bool(
            TkWebView2 is not None
            and sys.platform.startswith("win")
            and (webview2_runtime_available() if callable(webview2_runtime_available) else False)
        )
        self.visualizer_popup_webview_enabled = bool(
            (not self.visualizer_embed_enabled) and has_pywebview()
        )
        self.visualizer_webview = None
        self.visualizer_point_rows: list[dict] = []
        self.visualizer_nav_values: dict[str, list[float]] = {"n": [], "k": [], "density": []}
        self.visualizer_nav_index: dict[str, int] = {"n": 0, "k": 0, "density": 0}
        self.visualizer_nav_display_vars: dict[str, tk.StringVar] = {}
        self.visualizer_nav_count_vars: dict[str, tk.StringVar] = {}
        self.visualizer_nav_name_labels: dict[str, tk.Widget] = {}
        self.visualizer_nav_value_labels: dict[str, tk.Widget] = {}
        self.visualizer_nav_prev_buttons: dict[str, tk.Widget] = {}
        self.visualizer_nav_next_buttons: dict[str, tk.Widget] = {}
        self.visualizer_nav_jump_buttons: dict[str, dict[int, tk.Widget]] = {}
        self.visualizer_nav_rows: dict[str, tk.Widget] = {}
        self.visualizer_graph_canvas: FigureCanvasTkAgg | None = None
        self.visualizer_graph_fig: Figure | None = None
        self.visualizer_host_scroll_canvas: tk.Canvas | None = None
        self.visualizer_host_scroll_xbar: ttk.Scrollbar | None = None
        self.visualizer_host_scroll_ybar: ttk.Scrollbar | None = None
        self.visualizer_host_scroll_window = None
        self.visualizer_loaded_result: dict | None = None
        self.visualizer_active_context_key: str | None = None
        self.visualizer_bundle_cache_mem: dict[str, dict] = {}
        self.visualizer_cache_lock = threading.Lock()
        self.visualizer_prefetch_thread: threading.Thread | None = None
        self.visualizer_prefetch_context_key: str | None = None
        self.visualizer_prefetch_center_index: int | None = None
        self.visualizer_iterations: list[dict] = []
        self.visualizer_iteration_index = 0
        self.visualizer_solution_index = 0
        self.visualizer_iteration_label_var = tk.StringVar(value="Iteration --")
        self.visualizer_solution_label_var = tk.StringVar(value="Solution --")
        self.visualizer_solution_count_var = tk.StringVar(value="Solution Count: --")
        self.visualizer_no_solution_var = tk.StringVar(value="")
        self.visualizer_is_loading = False
        self.visualizer_autoplay_keys = ("iteration", "solution", "var_n", "var_k", "var_density")
        self.visualizer_autoplay_active: dict[str, bool] = {k: False for k in self.visualizer_autoplay_keys}
        self.visualizer_autoplay_label_vars: dict[str, tk.StringVar] = {
            k: tk.StringVar(value="Play") for k in self.visualizer_autoplay_keys
        }
        self.visualizer_autoplay_global_label_var = tk.StringVar(value="Start All")
        self.visualizer_autoplay_after_id: str | None = None
        self.visualizer_autoplay_current_key: str | None = None
        self.visualizer_autoplay_cycle_start_index: int | None = None
        self.visualizer_autoplay_cycle_steps = 0
        self.visualizer_autoplay_last_key: str | None = None
        self.visualizer_nav_play_buttons: dict[str, ttk.Button] = {}
        self.visualizer_iter_play_btn: ttk.Button | None = None
        self.visualizer_sol_play_btn: ttk.Button | None = None
        self.visualizer_global_autoplay_btn: ttk.Button | None = None
        self.visualizer_iter_back10_btn: ttk.Button | None = None
        self.visualizer_iter_back5_btn: ttk.Button | None = None
        self.visualizer_iter_prev_btn: ttk.Button | None = None
        self.visualizer_iter_next_btn: ttk.Button | None = None
        self.visualizer_iter_fwd5_btn: ttk.Button | None = None
        self.visualizer_iter_fwd10_btn: ttk.Button | None = None
        self.visualizer_sol_back10_btn: ttk.Button | None = None
        self.visualizer_sol_back5_btn: ttk.Button | None = None
        self.visualizer_sol_prev_btn: ttk.Button | None = None
        self.visualizer_sol_next_btn: ttk.Button | None = None
        self.visualizer_sol_fwd5_btn: ttk.Button | None = None
        self.visualizer_sol_fwd10_btn: ttk.Button | None = None
        self.visualizer_fullscreen_popup: tk.Toplevel | None = None
        self.visualizer_fullscreen_canvas: FigureCanvasTkAgg | None = None
        self.visualizer_fullscreen_fig: Figure | None = None
        self.visualizer_fullscreen_host: ttk.Frame | None = None
        self.visualizer_fullscreen_scroll_canvas: tk.Canvas | None = None
        self.visualizer_fullscreen_scroll_xbar: ttk.Scrollbar | None = None
        self.visualizer_fullscreen_scroll_ybar: ttk.Scrollbar | None = None
        self.visualizer_fullscreen_scroll_window = None
        self.visualizer_fullscreen_nav_rows: dict[str, ttk.Frame] = {}
        self.visualizer_fullscreen_nav_name_labels: dict[str, ttk.Label] = {}
        self.visualizer_fullscreen_nav_prev_buttons: dict[str, ttk.Button] = {}
        self.visualizer_fullscreen_nav_next_buttons: dict[str, ttk.Button] = {}
        self.visualizer_fullscreen_nav_jump_buttons: dict[str, dict[int, ttk.Button]] = {}
        self.visualizer_fullscreen_nav_play_buttons: dict[str, ttk.Button] = {}
        self.visualizer_fullscreen_iter_play_btn: ttk.Button | None = None
        self.visualizer_fullscreen_sol_play_btn: ttk.Button | None = None
        self.visualizer_fullscreen_global_autoplay_btn: ttk.Button | None = None
        self.visualizer_fullscreen_iter_back10_btn: ttk.Button | None = None
        self.visualizer_fullscreen_iter_back5_btn: ttk.Button | None = None
        self.visualizer_fullscreen_iter_prev_btn: ttk.Button | None = None
        self.visualizer_fullscreen_iter_next_btn: ttk.Button | None = None
        self.visualizer_fullscreen_iter_fwd5_btn: ttk.Button | None = None
        self.visualizer_fullscreen_iter_fwd10_btn: ttk.Button | None = None
        self.visualizer_fullscreen_sol_back10_btn: ttk.Button | None = None
        self.visualizer_fullscreen_sol_back5_btn: ttk.Button | None = None
        self.visualizer_fullscreen_sol_prev_btn: ttk.Button | None = None
        self.visualizer_fullscreen_sol_next_btn: ttk.Button | None = None
        self.visualizer_fullscreen_sol_fwd5_btn: ttk.Button | None = None
        self.visualizer_fullscreen_sol_fwd10_btn: ttk.Button | None = None
        self.datasets_canvas: tk.Canvas | None = None
        self.datasets_rows_frame: ttk.Frame | None = None
        self.datasets_scrollbar_x: ttk.Scrollbar | None = None
        self.datasets_scrollbar_y: ttk.Scrollbar | None = None
        self.dataset_checks: dict[str, tk.BooleanVar] = {}
        self.dataset_row_widgets: dict[str, dict[str, tk.Widget]] = {}
        self.dataset_download_jobs: dict[str, bool] = {}

        self._build_state()
        self._build_ui()
        self._apply_theme(self.current_theme_mode)
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)
        self._on_input_mode_tab_changed()
        self._on_tab_changed()
        self.after(0, self._apply_default_window_state)
        self.after(120, self._set_default_body_split)

    def _detect_system_theme_mode(self) -> str:
        # Windows: 0 means dark apps, 1 means light apps.
        if sys.platform.startswith("win") and winreg is not None:
            try:
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if int(value) != 0 else "dark"
            except Exception:
                pass

        # macOS: key exists and equals "Dark" when dark mode is enabled.
        if sys.platform == "darwin":
            try:
                res = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if res.returncode == 0 and "dark" in (res.stdout or "").strip().lower():
                    return "dark"
            except Exception:
                pass
            return "light"

        # Linux: prefer GNOME color-scheme, then GTK theme name hint.
        if sys.platform.startswith("linux"):
            try:
                res = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                raw = (res.stdout or "").strip().lower()
                if "dark" in raw:
                    return "dark"
                if "light" in raw:
                    return "light"
            except Exception:
                pass
            try:
                res = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                raw = (res.stdout or "").strip().lower()
                if "dark" in raw:
                    return "dark"
            except Exception:
                pass

        return "light"

    def _theme_palette(self) -> dict[str, str]:
        return self.current_theme_palette or THEME_PALETTES["light"]

    def _toggle_theme_mode(self):
        next_mode = "dark" if self.current_theme_mode == "light" else "light"
        self._apply_theme(next_mode)

    def _apply_log_tag_colors(self):
        if not hasattr(self, "log_box"):
            return
        palette = self._theme_palette()
        try:
            self.log_box.tag_configure("info", foreground=palette["log_info"])
            self.log_box.tag_configure("error", foreground=palette["log_error"])
            self.log_box.tag_configure("warn", foreground=palette["log_warn"])
            self.log_box.tag_configure("success", foreground=palette["log_success"])
            self.log_box.tag_configure("notice", foreground=palette["log_notice"])
        except Exception:
            pass

    def _apply_theme(self, mode: str):
        mode_key = "dark" if str(mode).strip().lower() == "dark" else "light"
        self.current_theme_mode = mode_key
        self.current_theme_palette = THEME_PALETTES.get(mode_key, THEME_PALETTES["light"])
        palette = self._theme_palette()

        try:
            theme_names = set(self.style.theme_names())
            if "clam" in theme_names:
                self.style.theme_use("clam")
        except Exception:
            pass

        self.configure(bg=palette["bg"])
        try:
            self.tk_setPalette(
                background=palette["bg"],
                foreground=palette["fg"],
                activeBackground=palette["button_active_bg"],
                activeForeground=palette["fg"],
                highlightColor=palette["accent"],
                selectBackground=palette["select_bg"],
                selectForeground=palette["select_fg"],
            )
        except Exception:
            pass

        self.style.configure(".", background=palette["bg"], foreground=palette["fg"])
        self.style.configure("TFrame", background=palette["bg"])
        self.style.configure("TLabelframe", background=palette["bg"])
        self.style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["fg"])
        self.style.configure("TLabel", background=palette["bg"], foreground=palette["fg"])
        self.style.configure("Muted.TLabel", background=palette["bg"], foreground=palette["muted_fg"])
        self.style.configure(
            "TButton",
            background=palette["button_bg"],
            foreground=palette["fg"],
        )
        self.style.map(
            "TButton",
            background=[("active", palette["button_active_bg"]), ("disabled", palette["button_bg"])],
            foreground=[("disabled", palette["muted_fg"])],
        )
        self.style.configure(
            "ThemeToggle.TButton",
            background=palette["button_bg"],
            foreground=palette["fg"],
            font=("Segoe UI", 9, "bold"),
            padding=(8, 4),
        )
        self.style.map(
            "ThemeToggle.TButton",
            background=[("active", palette["button_active_bg"])],
        )
        self.style.configure("TCheckbutton", background=palette["bg"], foreground=palette["fg"])
        self.style.configure("TRadiobutton", background=palette["bg"], foreground=palette["fg"])
        self.style.configure(
            "TEntry",
            fieldbackground=palette["input_bg"],
            foreground=palette["fg"],
            insertcolor=palette["fg"],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=palette["input_bg"],
            foreground=palette["fg"],
            selectbackground=palette["select_bg"],
            selectforeground=palette["select_fg"],
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette["input_bg"])],
            foreground=[("readonly", palette["fg"])],
            selectbackground=[("readonly", palette["select_bg"])],
            selectforeground=[("readonly", palette["select_fg"])],
        )
        self.style.configure("TNotebook", background=palette["bg"])
        self.style.configure("TNotebook.Tab", background=palette["tab_bg"], foreground=palette["fg"])
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", palette["tab_selected_bg"]), ("active", palette["button_active_bg"])],
            foreground=[("selected", palette["fg"])],
        )
        self.style.configure("TPanedwindow", background=palette["bg"])
        self.style.configure(
            "Stats.Treeview",
            background=palette["input_bg"],
            fieldbackground=palette["input_bg"],
            foreground=palette["fg"],
            bordercolor=palette["border"],
            rowheight=22,
        )
        self.style.map(
            "Stats.Treeview",
            background=[("selected", palette["select_bg"])],
            foreground=[("selected", palette["select_fg"])],
        )
        self.style.configure(
            "Stats.Treeview.Heading",
            background=palette["button_bg"],
            foreground=palette["fg"],
        )

        self.theme_toggle_label_var.set("Light Mode" if mode_key == "dark" else "Dark Mode")
        if self.theme_toggle_btn is not None:
            try:
                self.theme_toggle_btn.configure(style="ThemeToggle.TButton")
            except Exception:
                pass

        if hasattr(self, "_scroll_canvas"):
            try:
                self._scroll_canvas.configure(bg=palette["panel_bg"])
            except Exception:
                pass
        if hasattr(self, "datasets_canvas") and self.datasets_canvas is not None:
            try:
                self.datasets_canvas.configure(bg=palette["panel_bg"])
            except Exception:
                pass
        if hasattr(self, "log_box"):
            try:
                self.log_box.configure(
                    bg=palette["text_bg"],
                    fg=palette["text_fg"],
                    insertbackground=palette["text_fg"],
                    selectbackground=palette["select_bg"],
                    selectforeground=palette["select_fg"],
                )
            except Exception:
                pass
            self._apply_log_tag_colors()
        if hasattr(self, "parallel_status_label") and self.parallel_status_label is not None:
            try:
                self.parallel_status_label.configure(foreground=palette["muted_fg"], style="Muted.TLabel")
            except Exception:
                pass
        if hasattr(self, "outlier_filter_blurb") and self.outlier_filter_blurb is not None:
            try:
                self.outlier_filter_blurb.configure(foreground=palette["muted_fg"], style="Muted.TLabel")
            except Exception:
                pass
        if hasattr(self, "visualizer_embed_note") and self.visualizer_embed_note is not None:
            try:
                self.visualizer_embed_note.configure(foreground=palette["muted_fg"], style="Muted.TLabel")
            except Exception:
                pass
        if hasattr(self, "visualizer_status_label") and self.visualizer_status_label is not None:
            try:
                self.visualizer_status_label.configure(foreground=palette["muted_fg"], style="Muted.TLabel")
            except Exception:
                pass
        if hasattr(self, "visualizer_solution_count_label") and self.visualizer_solution_count_label is not None:
            try:
                self.visualizer_solution_count_label.configure(foreground=palette["muted_fg"], style="Muted.TLabel")
            except Exception:
                pass
        if hasattr(self, "visualizer_no_solution_label") and self.visualizer_no_solution_label is not None:
            try:
                self.visualizer_no_solution_label.configure(foreground=palette["log_error"])
            except Exception:
                pass
        if hasattr(self, "stats_blurb_label") and self.stats_blurb_label is not None:
            try:
                self.stats_blurb_label.configure(foreground=palette["muted_fg"], style="Muted.TLabel")
            except Exception:
                pass
        if hasattr(self, "stats_summary_label") and self.stats_summary_label is not None:
            try:
                self.stats_summary_label.configure(foreground=palette["muted_fg"], style="Muted.TLabel")
            except Exception:
                pass
        if hasattr(self, "stats_sort_note_label") and self.stats_sort_note_label is not None:
            try:
                self.stats_sort_note_label.configure(foreground=palette["muted_fg"], style="Muted.TLabel")
            except Exception:
                pass
        if hasattr(self, "stats_tree") and self.stats_tree is not None:
            try:
                self.stats_tree.tag_configure("significant", foreground=palette["log_success"])
                self.stats_tree.tag_configure("insufficient", foreground=palette["log_warn"])
            except Exception:
                pass

    def _build_state(self):
        self.tab_id_var = tk.StringVar(value="subgraph")
        self.input_mode_var = tk.StringVar(value="independent")
        self.iterations_var = tk.StringVar(value="5")
        self.seed_var = tk.StringVar(value="")
        self.run_mode_var = tk.StringVar(value="threshold")
        self.time_limit_minutes_var = tk.StringVar(value="10")
        self.solver_timeout_seconds_var = tk.StringVar(value="0")
        self.detected_logical_cores = int(psutil.cpu_count(logical=True) or os.cpu_count() or 1)
        self.parallel_enabled_var = tk.BooleanVar(value=self.detected_logical_cores > 1)
        default_workers = max(1, self.detected_logical_cores - 1)
        self.max_workers_var = tk.StringVar(value=str(default_workers))
        self.delete_generated_inputs_var = tk.BooleanVar(value=True)
        self.graph_family_var = tk.StringVar(value="random_density")
        self.plot3d_style_var = tk.StringVar(value="surface")
        self.plot3d_variant_var = tk.StringVar(value="")
        self.show_stddev_var = tk.BooleanVar(value=True)
        self.show_regression_var = tk.BooleanVar(value=False)
        self.show_trendlines_only_var = tk.BooleanVar(value=False)
        self.log_x_scale_var = tk.BooleanVar(value=False)
        self.log_y_scale_var = tk.BooleanVar(value=False)
        self.stats_blurb_var = tk.StringVar(
            value="Run a benchmark to populate runtime statistical comparisons."
        )
        self.stats_summary_var = tk.StringVar(
            value="No statistical comparisons available yet."
        )
        self.stats_sort_column_var = tk.StringVar(value="p-value")
        self.visualizer_status_var = tk.StringVar(
            value="Run a benchmark, then load a datapoint into the visualizer tab."
        )
        self.k_mode_var = tk.StringVar(value="percent")
        self.outlier_filter_var = tk.StringVar(value="none")
        self.failure_policy_var = tk.StringVar(value="continue")
        self.retry_failed_trials_var = tk.StringVar(value="0")
        self.timeout_as_missing_var = tk.BooleanVar(value=True)

        self.var_selected: dict[str, tk.BooleanVar] = {
            "n": tk.BooleanVar(value=True),
            "density": tk.BooleanVar(value=False),
            "k": tk.BooleanVar(value=False),
        }
        self.var_start: dict[str, tk.StringVar] = {
            "n": tk.StringVar(value="5"),
            "density": tk.StringVar(value="0.01"),
            "k": tk.StringVar(value="10"),
        }
        self.var_end: dict[str, tk.StringVar] = {
            "n": tk.StringVar(value=""),
            "density": tk.StringVar(value=""),
            "k": tk.StringVar(value=""),
        }
        self.var_step: dict[str, tk.StringVar] = {
            "n": tk.StringVar(value="1"),
            "density": tk.StringVar(value="0.01"),
            "k": tk.StringVar(value="1"),
        }

        self.variant_checks: dict[str, tk.BooleanVar] = {}
        for variant in SOLVER_VARIANTS:
            default = variant.tab_id == "subgraph"
            self.variant_checks[variant.variant_id] = tk.BooleanVar(value=default)
        self.dataset_checks = {}
        for spec in self.dataset_specs:
            self.dataset_checks[spec.dataset_id] = tk.BooleanVar(value=False)

    def _build_ui(self):
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        top_bar = ttk.Frame(outer, padding=(8, 6, 8, 2))
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        top_bar.columnconfigure(0, weight=1)
        self.theme_toggle_btn = ttk.Button(
            top_bar,
            textvariable=self.theme_toggle_label_var,
            command=self._toggle_theme_mode,
            style="ThemeToggle.TButton",
        )
        self.theme_toggle_btn.grid(row=0, column=1, sticky="e")

        self._scroll_canvas = tk.Canvas(outer, highlightthickness=0)
        v_scroll = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=self._scroll_canvas.yview)
        h_scroll = ttk.Scrollbar(outer, orient=tk.HORIZONTAL, command=self._scroll_canvas.xview)
        self._scroll_canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        self._scroll_canvas.grid(row=1, column=0, sticky="nsew")
        v_scroll.grid(row=1, column=1, sticky="ns")
        h_scroll.grid(row=2, column=0, sticky="ew")

        root = ttk.Frame(self._scroll_canvas, padding=10)
        self._scroll_window = self._scroll_canvas.create_window((0, 0), window=root, anchor="nw")
        root.bind("<Configure>", self._on_root_content_configure)
        self._scroll_canvas.bind("<Configure>", self._on_scroll_canvas_configure)
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel_scroll)

        control_col = ttk.Frame(root)
        control_col.pack(fill=tk.X)

        tab_frame = ttk.Frame(control_col)
        tab_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(tab_frame, text="Algorithm Tab:", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self.main_tab = ttk.Notebook(tab_frame)
        self.main_tab.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        self.subgraph_tab = ttk.Frame(self.main_tab)
        self.shortest_tab = ttk.Frame(self.main_tab)
        self.main_tab.add(self.subgraph_tab, text="Subgraph Isomorphism")
        self.main_tab.add(self.shortest_tab, text="Shortest Path")
        self.main_tab.bind("<<NotebookTabChanged>>", lambda _evt: self._on_tab_changed())
        ttk.Label(
            control_col,
            text="Choose a tab, then check which variants to benchmark. Subgraph is selected by default.",
        ).pack(anchor="w", pady=(0, 6))

        self._build_variant_section(self.subgraph_tab, "subgraph")
        self._build_variant_section(self.shortest_tab, "shortest_path")

        settings_row = ttk.Frame(control_col)
        settings_row.pack(fill=tk.X, pady=(8, 8))
        settings_row.columnconfigure(0, weight=1, uniform="settings_cols")
        settings_row.columnconfigure(1, weight=1, uniform="settings_cols")

        params = ttk.LabelFrame(settings_row, text="Benchmark Settings", padding=10)
        params.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(
            params,
            text="Set iterations/seed, configure optional multi-core workers, then choose threshold or timed mode.",
        ).pack(anchor="w", pady=(0, 6))

        row1 = ttk.Frame(params)
        row1.pack(fill=tk.X, pady=(0, 6))
        row1.columnconfigure(0, weight=1)
        row1.columnconfigure(1, weight=1)

        left_col = ttk.Frame(row1)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right_col = ttk.Frame(row1)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right_col.columnconfigure(0, weight=1)
        right_col.columnconfigure(1, weight=0)

        ttk.Label(left_col, text="Iterations per datapoint").grid(row=0, column=0, sticky="w")
        ttk.Entry(left_col, textvariable=self.iterations_var, width=10).grid(row=0, column=1, padx=(8, 0), sticky="w")

        ttk.Label(left_col, text="Graph Family").grid(row=1, column=0, pady=(8, 0), sticky="w")
        self.graph_family_combo = ttk.Combobox(
            left_col,
            state="readonly",
            textvariable=self.graph_family_var,
            values=list(generator_mod.GRAPH_FAMILIES),
            width=16,
        )
        self.graph_family_combo.grid(row=1, column=1, pady=(8, 0), padx=(8, 0), sticky="w")

        ttk.Label(left_col, text="Stop Mode").grid(row=2, column=0, pady=(8, 0), sticky="w")
        mode_row = ttk.Frame(left_col)
        mode_row.grid(row=2, column=1, pady=(8, 0), padx=(8, 0), sticky="w")
        ttk.Radiobutton(mode_row, text="Threshold", variable=self.run_mode_var, value="threshold", command=self._on_run_mode_changed).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_row, text="Timed", variable=self.run_mode_var, value="timed", command=self._on_run_mode_changed).pack(side=tk.LEFT, padx=(8, 0))
        self.parallel_check = ttk.Checkbutton(
            left_col,
            text="Enable Multi-Core",
            variable=self.parallel_enabled_var,
            command=self._on_parallel_settings_changed,
        )
        self.parallel_check.grid(row=3, column=0, columnspan=2, pady=(8, 0), sticky="w")
        ttk.Checkbutton(
            left_col,
            text="Delete generated inputs after datapoint",
            variable=self.delete_generated_inputs_var,
        ).grid(row=4, column=0, columnspan=2, pady=(8, 0), sticky="w")

        ttk.Label(right_col, text="Seed (blank = random)").grid(row=0, column=0, sticky="w")
        ttk.Entry(right_col, textvariable=self.seed_var, width=18).grid(row=0, column=1, padx=(8, 0), sticky="w")
        ttk.Label(right_col, text="Time Limit (minutes)").grid(row=1, column=0, pady=(8, 0), sticky="w")
        self.time_limit_entry = ttk.Entry(right_col, textvariable=self.time_limit_minutes_var, width=10)
        self.time_limit_entry.grid(row=1, column=1, pady=(8, 0), padx=(8, 0), sticky="w")
        ttk.Label(right_col, text="Max Parallel Workers").grid(row=2, column=0, pady=(8, 0), sticky="w")
        self.parallel_workers_entry = ttk.Entry(right_col, textvariable=self.max_workers_var, width=10)
        self.parallel_workers_entry.grid(row=2, column=1, pady=(8, 0), padx=(8, 0), sticky="w")
        ttk.Label(right_col, text="Solver Timeout (sec, 0=off)").grid(row=3, column=0, pady=(8, 0), sticky="w")
        self.solver_timeout_entry = ttk.Entry(right_col, textvariable=self.solver_timeout_seconds_var, width=10)
        self.solver_timeout_entry.grid(row=3, column=1, pady=(8, 0), padx=(8, 0), sticky="w")
        self.parallel_status_label = ttk.Label(
            right_col,
            text=f"Detected logical CPU threads: {self.detected_logical_cores}",
            style="Muted.TLabel",
        )
        self.parallel_status_label.grid(row=4, column=0, columnspan=2, pady=(8, 0), sticky="w")
        ttk.Label(right_col, text="Failure Policy").grid(row=5, column=0, pady=(8, 0), sticky="w")
        self.failure_policy_combo = ttk.Combobox(
            right_col,
            state="readonly",
            textvariable=self.failure_policy_var,
            values=["stop", "continue"],
            width=12,
        )
        self.failure_policy_combo.grid(row=5, column=1, pady=(8, 0), padx=(8, 0), sticky="w")
        ttk.Label(right_col, text="Retry Failed Trials").grid(row=6, column=0, pady=(8, 0), sticky="w")
        ttk.Entry(right_col, textvariable=self.retry_failed_trials_var, width=10).grid(row=6, column=1, pady=(8, 0), padx=(8, 0), sticky="w")
        ttk.Checkbutton(
            right_col,
            text="Treat timeout as missing",
            variable=self.timeout_as_missing_var,
        ).grid(row=7, column=0, columnspan=2, pady=(8, 0), sticky="w")
        ttk.Label(right_col, text="Outlier Filter").grid(row=8, column=0, pady=(8, 0), sticky="w")
        self.outlier_filter_combo = ttk.Combobox(
            right_col,
            state="readonly",
            textvariable=self.outlier_filter_var,
            values=["none", "mad", "iqr"],
            width=12,
        )
        self.outlier_filter_combo.grid(row=8, column=1, pady=(8, 0), padx=(8, 0), sticky="w")
        self.outlier_filter_combo.bind("<<ComboboxSelected>>", lambda _evt: self._on_outlier_filter_changed())
        self.outlier_filter_blurb = ttk.Label(
            right_col,
            text="",
            style="Muted.TLabel",
            wraplength=260,
            justify=tk.LEFT,
        )
        right_col.bind("<Configure>", self._on_outlier_blurb_parent_resize)
        self._on_outlier_filter_changed()

        sweep = ttk.LabelFrame(settings_row, text="Independent Variables / Datasets", padding=10)
        sweep.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.input_source_tabs = ttk.Notebook(sweep)
        self.input_source_tabs.pack(fill=tk.BOTH, expand=True)
        independent_tab = ttk.Frame(self.input_source_tabs)
        datasets_tab = ttk.Frame(self.input_source_tabs)
        self.input_source_tabs.add(independent_tab, text="Independent Variables")
        self.input_source_tabs.add(datasets_tab, text="Datasets")
        self.input_source_tabs.bind("<<NotebookTabChanged>>", lambda _evt: self._on_input_mode_tab_changed())
        self._build_independent_variable_controls(independent_tab)
        self._build_datasets_controls(datasets_tab)

        render_opts = ttk.LabelFrame(control_col, text="3D Options (used when two independent variables are selected)", padding=10)
        render_opts.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            render_opts,
            text="Pick the 3D plot style and which single variant to render when two independent variables are selected.",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        ttk.Label(render_opts, text="3D Style").grid(row=1, column=0, sticky="w")
        self.style_combo = ttk.Combobox(render_opts, state="readonly", textvariable=self.plot3d_style_var, values=["surface", "wireframe", "scatter"], width=14)
        self.style_combo.grid(row=1, column=1, padx=(8, 20), sticky="w")
        self.style_combo.bind("<<ComboboxSelected>>", lambda _evt: self._repaint_existing_plots())
        ttk.Label(render_opts, text="3D Variant").grid(row=1, column=2, sticky="w")
        self.variant_combo = ttk.Combobox(render_opts, state="readonly", textvariable=self.plot3d_variant_var, values=[], width=30)
        self.variant_combo.grid(row=1, column=3, padx=(8, 0), sticky="w")
        self.variant_combo.bind("<<ComboboxSelected>>", lambda _evt: self._repaint_existing_plots())

        actions = ttk.Frame(control_col)
        actions.pack(fill=tk.X, pady=(0, 8))
        self.run_btn = ttk.Button(actions, text="Run Benchmark", command=self._start_run)
        self.run_btn.pack(side=tk.LEFT)
        self.abort_btn = ttk.Button(actions, text="Abort Test", command=self._abort_run, state=tk.DISABLED)
        self.abort_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.pause_btn = ttk.Button(actions, text="Pause", command=self._toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.estimate_btn = ttk.Button(actions, text="Estimate Run", command=self._estimate_run)
        self.estimate_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.open_dir_btn = ttk.Button(actions, text="Open Output Folder", command=self._open_output_dir, state=tk.DISABLED)
        self.open_dir_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.export_manifest_btn = ttk.Button(actions, text="Export Manifest", command=self._export_reproducible_manifest)
        self.export_manifest_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.import_manifest_btn = ttk.Button(actions, text="Import Manifest", command=self._import_reproducible_manifest)
        self.import_manifest_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.save_btn = ttk.Button(actions, text="Save Exports Again", command=self._save_exports_again, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.clear_log_btn = ttk.Button(actions, text="Clear Log", command=self._clear_run_log)
        self.clear_log_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.clear_graphs_btn = ttk.Button(actions, text="Clear Graphs", command=lambda: self._clear_graphs(announce=True))
        self.clear_graphs_btn.pack(side=tk.LEFT, padx=(8, 0))

        body = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)
        self.body_pane = body

        log_container = ttk.Frame(body, padding=6)
        log_header = ttk.Frame(log_container)
        log_header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(log_header, text="Run Log", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self.run_log_timer_label = ttk.Label(log_header, text="", font=("Consolas", 10, "bold"))
        self.log_box = ScrolledText(log_container, height=16, wrap=tk.WORD)
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self._apply_log_tag_colors()
        self.log_box.configure(state=tk.DISABLED)
        body.add(log_container, weight=1)

        chart_panel = ttk.Notebook(body)
        self.chart_panel = chart_panel
        body.add(chart_panel, weight=1)

        runtime_tab = ttk.Frame(chart_panel)
        memory_tab = ttk.Frame(chart_panel)
        runtime_3d_tab = ttk.Frame(chart_panel)
        memory_3d_tab = ttk.Frame(chart_panel)
        stats_tab = ttk.Frame(chart_panel)
        visualizer_tab = ttk.Frame(chart_panel)
        chart_panel.add(runtime_tab, text="Runtime 2D")
        chart_panel.add(memory_tab, text="Memory 2D")
        chart_panel.add(runtime_3d_tab, text="Runtime 3D")
        chart_panel.add(memory_3d_tab, text="Memory 3D")
        chart_panel.add(stats_tab, text="Statistics")
        chart_panel.add(visualizer_tab, text="Visualizer")

        runtime_toolbar = ttk.Frame(runtime_tab)
        runtime_toolbar.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Checkbutton(
            runtime_toolbar,
            text="Show SD Bars",
            variable=self.show_stddev_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            runtime_toolbar,
            text="Show Regression Line",
            variable=self.show_regression_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            runtime_toolbar,
            text="Trendlines Only",
            variable=self.show_trendlines_only_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            runtime_toolbar,
            text="Log X",
            variable=self.log_x_scale_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            runtime_toolbar,
            text="Log Y",
            variable=self.log_y_scale_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(runtime_toolbar, text="Fullscreen", command=lambda: self._open_graph_fullscreen("runtime_2d")).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(runtime_toolbar, text="Save Graph", command=lambda: self._save_graph_from_tab("runtime_2d")).pack(side=tk.RIGHT)
        self.runtime_frame = ttk.Frame(runtime_tab)
        self.runtime_frame.pack(fill=tk.BOTH, expand=True)

        memory_toolbar = ttk.Frame(memory_tab)
        memory_toolbar.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Checkbutton(
            memory_toolbar,
            text="Show SD Bars",
            variable=self.show_stddev_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            memory_toolbar,
            text="Show Regression Line",
            variable=self.show_regression_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            memory_toolbar,
            text="Trendlines Only",
            variable=self.show_trendlines_only_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            memory_toolbar,
            text="Log X",
            variable=self.log_x_scale_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            memory_toolbar,
            text="Log Y",
            variable=self.log_y_scale_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(memory_toolbar, text="Fullscreen", command=lambda: self._open_graph_fullscreen("memory_2d")).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(memory_toolbar, text="Save Graph", command=lambda: self._save_graph_from_tab("memory_2d")).pack(side=tk.RIGHT)
        self.memory_frame = ttk.Frame(memory_tab)
        self.memory_frame.pack(fill=tk.BOTH, expand=True)

        runtime3d_toolbar = ttk.Frame(runtime_3d_tab)
        runtime3d_toolbar.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Checkbutton(
            runtime3d_toolbar,
            text="Log X",
            variable=self.log_x_scale_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            runtime3d_toolbar,
            text="Log Y",
            variable=self.log_y_scale_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(runtime3d_toolbar, text="Fullscreen", command=lambda: self._open_graph_fullscreen("runtime_3d")).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(runtime3d_toolbar, text="Save Graph", command=lambda: self._save_graph_from_tab("runtime_3d")).pack(side=tk.RIGHT)
        ttk.Button(runtime3d_toolbar, text="Center", command=lambda: self._center_3d_view("runtime")).pack(side=tk.RIGHT, padx=(0, 8))
        self.runtime_3d_frame = ttk.Frame(runtime_3d_tab)
        self.runtime_3d_frame.pack(fill=tk.BOTH, expand=True)

        memory3d_toolbar = ttk.Frame(memory_3d_tab)
        memory3d_toolbar.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Checkbutton(
            memory3d_toolbar,
            text="Log X",
            variable=self.log_x_scale_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            memory3d_toolbar,
            text="Log Y",
            variable=self.log_y_scale_var,
            command=self._repaint_existing_plots,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(memory3d_toolbar, text="Fullscreen", command=lambda: self._open_graph_fullscreen("memory_3d")).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(memory3d_toolbar, text="Save Graph", command=lambda: self._save_graph_from_tab("memory_3d")).pack(side=tk.RIGHT)
        ttk.Button(memory3d_toolbar, text="Center", command=lambda: self._center_3d_view("memory")).pack(side=tk.RIGHT, padx=(0, 8))
        self.memory_3d_frame = ttk.Frame(memory_3d_tab)
        self.memory_3d_frame.pack(fill=tk.BOTH, expand=True)

        self.stats_wrap = ttk.Frame(stats_tab, padding=10)
        self.stats_wrap.pack(fill=tk.BOTH, expand=True)
        self.stats_blurb_label = ttk.Label(
            self.stats_wrap,
            textvariable=self.stats_blurb_var,
            style="Muted.TLabel",
            justify=tk.LEFT,
            wraplength=800,
        )
        self.stats_blurb_label.pack(fill=tk.X, anchor="w")
        self.stats_summary_label = ttk.Label(
            self.stats_wrap,
            textvariable=self.stats_summary_var,
            style="Muted.TLabel",
            justify=tk.LEFT,
            wraplength=800,
        )
        self.stats_summary_label.pack(fill=tk.X, anchor="w", pady=(4, 8))

        stats_controls = ttk.Frame(self.stats_wrap)
        stats_controls.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(stats_controls, text="Sort by:").pack(side=tk.LEFT)
        stats_table_wrap = ttk.Frame(self.stats_wrap)
        stats_table_wrap.pack(fill=tk.BOTH, expand=True)
        stats_columns = (
            "variant",
            "baseline",
            "n",
            "p_value",
            "direction",
            "mean_delta_ms",
            "ci95_ms",
            "hedges_g",
            "cliffs_delta",
            "mode",
        )
        heading_map = self._stats_column_heading_map()
        sort_labels = [heading_map.get(col, col) for col in stats_columns]
        default_sort_label = heading_map.get("p_value", "p-value")
        if default_sort_label not in sort_labels and sort_labels:
            default_sort_label = sort_labels[0]
        self.stats_sort_column_var.set(default_sort_label)
        self.stats_sort_column_combo = ttk.Combobox(
            stats_controls,
            state="readonly",
            textvariable=self.stats_sort_column_var,
            values=sort_labels,
            width=20,
        )
        self.stats_sort_column_combo.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(
            stats_controls,
            text="\u2191",
            width=3,
            command=lambda: self._sort_stats_tree(ascending=True),
        ).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Button(
            stats_controls,
            text="\u2193",
            width=3,
            command=lambda: self._sort_stats_tree(ascending=False),
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.stats_sort_note_label = ttk.Label(
            stats_controls,
            text="Use arrows to sort. Click a header for help.",
            style="Muted.TLabel",
        )
        self.stats_sort_note_label.pack(side=tk.LEFT)

        self.stats_tree = ttk.Treeview(
            stats_table_wrap,
            columns=stats_columns,
            show="headings",
            style="Stats.Treeview",
        )
        for col in stats_columns:
            self.stats_tree.heading(
                col,
                text=heading_map.get(col, col),
                command=lambda c=col: self._show_stats_heading_help(c),
            )
        self.stats_tree.column("variant", width=180, anchor="w", stretch=False)
        self.stats_tree.column("baseline", width=180, anchor="w", stretch=False)
        self.stats_tree.column("n", width=60, anchor="center", stretch=False)
        self.stats_tree.column("p_value", width=90, anchor="e", stretch=False)
        self.stats_tree.column("direction", width=100, anchor="center", stretch=False)
        self.stats_tree.column("mean_delta_ms", width=120, anchor="e", stretch=False)
        self.stats_tree.column("ci95_ms", width=180, anchor="e", stretch=False)
        self.stats_tree.column("hedges_g", width=100, anchor="e", stretch=False)
        self.stats_tree.column("cliffs_delta", width=110, anchor="e", stretch=False)
        self.stats_tree.column("mode", width=80, anchor="center", stretch=False)
        stats_ybar = ttk.Scrollbar(stats_table_wrap, orient=tk.VERTICAL, command=self.stats_tree.yview)
        stats_xbar = ttk.Scrollbar(stats_table_wrap, orient=tk.HORIZONTAL, command=self.stats_tree.xview)
        self.stats_tree.configure(yscrollcommand=stats_ybar.set, xscrollcommand=stats_xbar.set)
        self.stats_tree.grid(row=0, column=0, sticky="nsew")
        stats_ybar.grid(row=0, column=1, sticky="ns")
        stats_xbar.grid(row=1, column=0, sticky="ew")
        stats_table_wrap.grid_rowconfigure(0, weight=1)
        stats_table_wrap.grid_columnconfigure(0, weight=1)
        self.stats_wrap.bind("<Configure>", self._refresh_stats_blurb_wraplength)

        vis_wrap = ttk.Frame(visualizer_tab, padding=12)
        vis_wrap.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            vis_wrap,
            text=(
                "Use variable navigators to choose a datapoint tuple. "
                "The visualizer renders in this tab and supports iteration/solution navigation."
            ),
            wraplength=760,
            justify=tk.LEFT,
        ).pack(anchor="w")
        vis_var_frame = ttk.Frame(vis_wrap)
        vis_var_frame.pack(fill=tk.X, pady=(10, 4))
        self.visualizer_var_frame = vis_var_frame
        ttk.Label(vis_var_frame, text="Datapoint Selection:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        for var_id in ("n", "k", "density"):
            row = ttk.Frame(vis_var_frame)
            row.pack(fill=tk.X, pady=(1, 1))
            lbl = ttk.Label(row, text=f"{self._axis_label(var_id)}:", width=12)
            lbl.pack(side=tk.LEFT)
            back10_btn = ttk.Button(row, text="<<<", width=4, command=lambda v=var_id: self._shift_visualizer_variable(v, -10))
            back10_btn.pack(side=tk.LEFT)
            back5_btn = ttk.Button(row, text="<<", width=4, command=lambda v=var_id: self._shift_visualizer_variable(v, -5))
            back5_btn.pack(side=tk.LEFT, padx=(2, 0))
            prev_btn = ttk.Button(row, text="<", width=3, command=lambda v=var_id: self._shift_visualizer_variable(v, -1))
            prev_btn.pack(side=tk.LEFT, padx=(2, 0))
            value_var = tk.StringVar(value="--")
            value_label = tk.Label(row, textvariable=value_var, width=16, anchor="center", fg="#666666")
            value_label.pack(side=tk.LEFT, padx=(6, 6))
            next_btn = ttk.Button(row, text=">", width=3, command=lambda v=var_id: self._shift_visualizer_variable(v, 1))
            next_btn.pack(side=tk.LEFT)
            fwd5_btn = ttk.Button(row, text=">>", width=4, command=lambda v=var_id: self._shift_visualizer_variable(v, 5))
            fwd5_btn.pack(side=tk.LEFT, padx=(2, 0))
            fwd10_btn = ttk.Button(row, text=">>>", width=4, command=lambda v=var_id: self._shift_visualizer_variable(v, 10))
            fwd10_btn.pack(side=tk.LEFT, padx=(2, 0))
            count_var = tk.StringVar(value="(0/0)")
            count_label = ttk.Label(row, textvariable=count_var, foreground="#666666")
            count_label.pack(side=tk.LEFT, padx=(8, 0))
            auto_key = f"var_{var_id}"
            play_btn = ttk.Button(
                row,
                textvariable=self.visualizer_autoplay_label_vars[auto_key],
                width=6,
                command=lambda k=auto_key: self._toggle_visualizer_autoplay(k),
                state=tk.DISABLED,
            )
            play_btn.pack(side=tk.LEFT, padx=(8, 0))
            self.visualizer_nav_rows[var_id] = row
            self.visualizer_nav_display_vars[var_id] = value_var
            self.visualizer_nav_count_vars[var_id] = count_var
            self.visualizer_nav_name_labels[var_id] = lbl
            self.visualizer_nav_value_labels[var_id] = value_label
            self.visualizer_nav_prev_buttons[var_id] = prev_btn
            self.visualizer_nav_next_buttons[var_id] = next_btn
            self.visualizer_nav_play_buttons[var_id] = play_btn
            self.visualizer_nav_jump_buttons[var_id] = {
                -10: back10_btn,
                -5: back5_btn,
                -1: prev_btn,
                1: next_btn,
                5: fwd5_btn,
                10: fwd10_btn,
            }

        vis_iter_sol_frame = ttk.Frame(vis_wrap)
        vis_iter_sol_frame.pack(fill=tk.X, pady=(6, 6))
        ttk.Label(vis_iter_sol_frame, text="Iteration:", width=10).pack(side=tk.LEFT)
        self.visualizer_iter_back10_btn = ttk.Button(
            vis_iter_sol_frame, text="<<<", width=4, command=lambda: self._visualizer_shift_iteration(-10), state=tk.DISABLED
        )
        self.visualizer_iter_back10_btn.pack(side=tk.LEFT)
        self.visualizer_iter_back5_btn = ttk.Button(
            vis_iter_sol_frame, text="<<", width=4, command=lambda: self._visualizer_shift_iteration(-5), state=tk.DISABLED
        )
        self.visualizer_iter_back5_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_iter_prev_btn = ttk.Button(
            vis_iter_sol_frame, text="<", width=3, command=lambda: self._visualizer_shift_iteration(-1), state=tk.DISABLED
        )
        self.visualizer_iter_prev_btn.pack(side=tk.LEFT)
        ttk.Label(vis_iter_sol_frame, textvariable=self.visualizer_iteration_label_var, width=20).pack(side=tk.LEFT, padx=(6, 6))
        self.visualizer_iter_next_btn = ttk.Button(
            vis_iter_sol_frame, text=">", width=3, command=lambda: self._visualizer_shift_iteration(1), state=tk.DISABLED
        )
        self.visualizer_iter_next_btn.pack(side=tk.LEFT)
        self.visualizer_iter_fwd5_btn = ttk.Button(
            vis_iter_sol_frame, text=">>", width=4, command=lambda: self._visualizer_shift_iteration(5), state=tk.DISABLED
        )
        self.visualizer_iter_fwd5_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_iter_fwd10_btn = ttk.Button(
            vis_iter_sol_frame, text=">>>", width=4, command=lambda: self._visualizer_shift_iteration(10), state=tk.DISABLED
        )
        self.visualizer_iter_fwd10_btn.pack(side=tk.LEFT, padx=(2, 12))
        ttk.Label(vis_iter_sol_frame, text="Solution:", width=10).pack(side=tk.LEFT)
        self.visualizer_sol_back10_btn = ttk.Button(
            vis_iter_sol_frame, text="<<<", width=4, command=lambda: self._visualizer_shift_solution(-10), state=tk.DISABLED
        )
        self.visualizer_sol_back10_btn.pack(side=tk.LEFT)
        self.visualizer_sol_back5_btn = ttk.Button(
            vis_iter_sol_frame, text="<<", width=4, command=lambda: self._visualizer_shift_solution(-5), state=tk.DISABLED
        )
        self.visualizer_sol_back5_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_sol_prev_btn = ttk.Button(
            vis_iter_sol_frame, text="<", width=3, command=lambda: self._visualizer_shift_solution(-1), state=tk.DISABLED
        )
        self.visualizer_sol_prev_btn.pack(side=tk.LEFT)
        ttk.Label(vis_iter_sol_frame, textvariable=self.visualizer_solution_label_var, width=28).pack(side=tk.LEFT, padx=(6, 6))
        self.visualizer_sol_next_btn = ttk.Button(
            vis_iter_sol_frame, text=">", width=3, command=lambda: self._visualizer_shift_solution(1), state=tk.DISABLED
        )
        self.visualizer_sol_next_btn.pack(side=tk.LEFT)
        self.visualizer_sol_fwd5_btn = ttk.Button(
            vis_iter_sol_frame, text=">>", width=4, command=lambda: self._visualizer_shift_solution(5), state=tk.DISABLED
        )
        self.visualizer_sol_fwd5_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_sol_fwd10_btn = ttk.Button(
            vis_iter_sol_frame, text=">>>", width=4, command=lambda: self._visualizer_shift_solution(10), state=tk.DISABLED
        )
        self.visualizer_sol_fwd10_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_iter_play_btn = ttk.Button(
            vis_iter_sol_frame,
            textvariable=self.visualizer_autoplay_label_vars["iteration"],
            width=6,
            command=lambda: self._toggle_visualizer_autoplay("iteration"),
            state=tk.DISABLED,
        )
        self.visualizer_iter_play_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.visualizer_sol_play_btn = ttk.Button(
            vis_iter_sol_frame,
            textvariable=self.visualizer_autoplay_label_vars["solution"],
            width=6,
            command=lambda: self._toggle_visualizer_autoplay("solution"),
            state=tk.DISABLED,
        )
        self.visualizer_sol_play_btn.pack(side=tk.LEFT, padx=(8, 0))

        vis_controls = ttk.Frame(vis_wrap)
        vis_controls.pack(fill=tk.X, pady=(2, 4))
        self.load_visualizer_btn = ttk.Button(
            vis_controls,
            text="Load In Tab",
            command=self._load_visualizer_in_tab,
            state=tk.DISABLED,
        )
        self.load_visualizer_btn.pack(side=tk.LEFT)
        self.open_visualizer_btn = ttk.Button(
            vis_controls,
            text="Open External",
            command=self._open_visualizer_external,
            state=tk.DISABLED,
        )
        self.open_visualizer_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.visualizer_fullscreen_btn = ttk.Button(
            vis_controls,
            text="Fullscreen",
            command=self._open_visualizer_fullscreen,
            state=tk.DISABLED,
        )
        self.visualizer_fullscreen_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.visualizer_global_autoplay_btn = ttk.Button(
            vis_controls,
            textvariable=self.visualizer_autoplay_global_label_var,
            command=self._toggle_visualizer_autoplay_all,
            state=tk.DISABLED,
        )
        self.visualizer_global_autoplay_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.visualizer_embed_note = ttk.Label(
            vis_wrap,
            text="Open External uses the website visualizer in your browser.",
            style="Muted.TLabel",
            wraplength=760,
            justify=tk.LEFT,
        )
        self.visualizer_embed_note.pack(anchor="w", pady=(0, 4))
        self.visualizer_status_label = ttk.Label(
            vis_wrap,
            textvariable=self.visualizer_status_var,
            style="Muted.TLabel",
            wraplength=760,
            justify=tk.LEFT,
        )
        self.visualizer_status_label.pack(anchor="w", pady=(0, 6))
        self.visualizer_solution_count_label = ttk.Label(
            vis_wrap,
            textvariable=self.visualizer_solution_count_var,
            style="Muted.TLabel",
            justify=tk.LEFT,
        )
        self.visualizer_solution_count_label.pack(anchor="w", pady=(0, 2))
        self.visualizer_no_solution_label = ttk.Label(
            vis_wrap,
            textvariable=self.visualizer_no_solution_var,
            foreground="#B00020",
            justify=tk.LEFT,
        )
        self.visualizer_no_solution_label.pack(anchor="w", pady=(0, 6))
        vis_graph_wrap = ttk.Frame(vis_wrap)
        vis_graph_wrap.pack(fill=tk.BOTH, expand=True)
        vis_graph_wrap.grid_rowconfigure(0, weight=1)
        vis_graph_wrap.grid_columnconfigure(0, weight=1)
        self.visualizer_host_scroll_canvas = tk.Canvas(vis_graph_wrap, highlightthickness=0, borderwidth=0)
        self.visualizer_host_scroll_ybar = ttk.Scrollbar(
            vis_graph_wrap, orient=tk.VERTICAL, command=self.visualizer_host_scroll_canvas.yview
        )
        self.visualizer_host_scroll_xbar = ttk.Scrollbar(
            vis_graph_wrap, orient=tk.HORIZONTAL, command=self.visualizer_host_scroll_canvas.xview
        )
        self.visualizer_host_scroll_canvas.configure(
            yscrollcommand=self.visualizer_host_scroll_ybar.set,
            xscrollcommand=self.visualizer_host_scroll_xbar.set,
        )
        self.visualizer_host_scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self.visualizer_host_scroll_ybar.grid(row=0, column=1, sticky="ns")
        self.visualizer_host_scroll_xbar.grid(row=1, column=0, sticky="ew")
        self.visualizer_host_frame = ttk.Frame(self.visualizer_host_scroll_canvas)
        self.visualizer_host_scroll_window = self.visualizer_host_scroll_canvas.create_window(
            (0, 0), window=self.visualizer_host_frame, anchor="nw"
        )
        self.visualizer_host_frame.bind("<Configure>", self._refresh_visualizer_host_scrollregion)
        self.visualizer_host_scroll_canvas.bind("<Configure>", self._refresh_visualizer_host_scrollregion)
        self.after(0, self._refresh_visualizer_host_scrollregion)

        self.runtime_canvas: FigureCanvasTkAgg | None = None
        self.memory_canvas: FigureCanvasTkAgg | None = None
        self.runtime_3d_canvas: FigureCanvasTkAgg | None = None
        self.memory_3d_canvas: FigureCanvasTkAgg | None = None

    def _on_root_content_configure(self, _evt):
        self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _on_scroll_canvas_configure(self, evt):
        self._scroll_canvas.itemconfigure(self._scroll_window, width=evt.width)

    def _on_mousewheel_scroll(self, evt):
        delta = int(getattr(evt, "delta", 0))
        if delta != 0:
            self._scroll_canvas.yview_scroll(int(-delta / 120), "units")

    def _refresh_visualizer_host_scrollregion(self, _evt=None):
        canvas = self.visualizer_host_scroll_canvas
        if canvas is None:
            return
        try:
            bbox = canvas.bbox("all")
            canvas.configure(scrollregion=(bbox if bbox else (0, 0, 0, 0)))
        except Exception:
            pass

    def _refresh_visualizer_fullscreen_scrollregion(self, _evt=None):
        canvas = self.visualizer_fullscreen_scroll_canvas
        if canvas is None:
            return
        try:
            bbox = canvas.bbox("all")
            canvas.configure(scrollregion=(bbox if bbox else (0, 0, 0, 0)))
        except Exception:
            pass

    def _apply_default_window_state(self):
        try:
            self.attributes("-fullscreen", False)
        except Exception:
            pass
        try:
            self.state("zoomed")
            return
        except Exception:
            pass
        try:
            self.attributes("-zoomed", True)
            return
        except Exception:
            pass
        try:
            self.update_idletasks()
            self.geometry(f"{int(self.winfo_screenwidth())}x{int(self.winfo_screenheight())}+0+0")
        except Exception:
            pass

    def _set_default_body_split(self):
        pane = getattr(self, "body_pane", None)
        if pane is None:
            return
        try:
            self.update_idletasks()
            width = int(pane.winfo_width())
            if width > 100:
                pane.sashpos(0, width // 2)
        except Exception:
            pass

    def _build_independent_variable_controls(self, parent: ttk.Frame):
        ttk.Label(
            parent,
            text="Select up to two variables to sweep. For unselected variables, Start is treated as the fixed value.",
        ).grid(row=0, column=0, columnspan=5, sticky="w", padx=4, pady=(0, 8))
        ttk.Label(parent, text="K Mode").grid(row=1, column=0, sticky="w", padx=4, pady=(0, 8))
        self.k_mode_combo = ttk.Combobox(
            parent,
            state="readonly",
            textvariable=self.k_mode_var,
            values=["percent", "absolute"],
            width=12,
        )
        self.k_mode_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=4, pady=(0, 8))
        self.k_mode_combo.bind("<<ComboboxSelected>>", lambda _evt: self._on_variable_selection_changed())
        headers = ["Use", "Variable", "Start", "End", "Step"]
        for col, header in enumerate(headers):
            ttk.Label(parent, text=header, font=("Segoe UI", 9, "bold")).grid(row=2, column=col, sticky="w", padx=4, pady=(0, 6))

        self.sweep_rows = {}
        ordered = [("n", "N"), ("density", "Density"), ("k", "k % of N")]
        for i, (var_id, label) in enumerate(ordered, start=3):
            use_cb = ttk.Checkbutton(parent, variable=self.var_selected[var_id], command=self._on_variable_selection_changed)
            use_cb.grid(row=i, column=0, padx=4, sticky="w")
            name_label = ttk.Label(parent, text=label)
            name_label.grid(row=i, column=1, padx=4, sticky="w")
            start_entry = ttk.Entry(parent, textvariable=self.var_start[var_id], width=12)
            start_entry.grid(row=i, column=2, padx=4, sticky="w")
            end_entry = ttk.Entry(parent, textvariable=self.var_end[var_id], width=12)
            end_entry.grid(row=i, column=3, padx=4, sticky="w")
            step_entry = ttk.Entry(parent, textvariable=self.var_step[var_id], width=12)
            step_entry.grid(row=i, column=4, padx=4, sticky="w")
            self.sweep_rows[var_id] = {
                "use_cb": use_cb,
                "label": name_label,
                "start": start_entry,
                "end": end_entry,
                "step": step_entry,
            }

    def _build_datasets_controls(self, parent: ttk.Frame):
        ttk.Label(
            parent,
            text=(
                "Use this tab to benchmark downloaded external datasets. "
                "Each row tracks raw download and converted-ready status."
            ),
            justify=tk.LEFT,
            wraplength=560,
        ).pack(fill=tk.X, pady=(0, 6))

        tools = ttk.Frame(parent)
        tools.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(tools, text="Check All", command=lambda: self._set_all_datasets_for_current_tab(True)).pack(side=tk.LEFT)
        ttk.Button(tools, text="Clear All", command=lambda: self._set_all_datasets_for_current_tab(False)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(tools, text="Download Selected", command=self._download_selected_datasets).pack(side=tk.LEFT, padx=(16, 0))

        table_wrap = ttk.Frame(parent)
        table_wrap.pack(fill=tk.BOTH, expand=True)
        table_wrap.columnconfigure(0, weight=1)
        table_wrap.rowconfigure(0, weight=1)

        canvas = tk.Canvas(
            table_wrap,
            highlightthickness=0,
            height=220,
            bg=self._theme_palette().get("panel_bg", self._theme_palette().get("bg", "#FFFFFF")),
        )
        y_scroll = ttk.Scrollbar(table_wrap, orient=tk.VERTICAL, command=canvas.yview)
        x_scroll = ttk.Scrollbar(table_wrap, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        rows_frame = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=rows_frame, anchor="nw")

        def _refresh_scroll(_evt=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass

        rows_frame.bind("<Configure>", _refresh_scroll)
        canvas.bind("<Configure>", _refresh_scroll)

        def _on_mousewheel(evt):
            delta = int(getattr(evt, "delta", 0))
            if delta != 0:
                canvas.yview_scroll(int(-delta / 120), "units")
            else:
                btn_num = int(getattr(evt, "num", 0))
                if btn_num == 4:
                    canvas.yview_scroll(-1, "units")
                elif btn_num == 5:
                    canvas.yview_scroll(1, "units")

        for widget in (canvas, rows_frame):
            widget.bind("<MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", _on_mousewheel)
            widget.bind("<Button-5>", _on_mousewheel)

        self.datasets_canvas = canvas
        self.datasets_rows_frame = rows_frame
        self.datasets_scrollbar_x = x_scroll
        self.datasets_scrollbar_y = y_scroll
        self.after(0, self._refresh_dataset_rows)

    def _on_input_mode_tab_changed(self):
        if not hasattr(self, "input_source_tabs") or self.input_source_tabs is None:
            self.input_mode_var.set("independent")
            return
        index = int(self.input_source_tabs.index(self.input_source_tabs.select()))
        self.input_mode_var.set("independent" if index == 0 else "datasets")

    def _input_mode(self) -> str:
        mode = str(self.input_mode_var.get() or "independent").strip().lower()
        return "datasets" if mode == "datasets" else "independent"

    def _dataset_specs_for_current_tab(self) -> list[DatasetSpec]:
        tab_id = self.tab_id_var.get()
        return [spec for spec in self.dataset_specs if spec.tab_id == tab_id]

    def _selected_dataset_specs_for_current_tab(self) -> list[DatasetSpec]:
        selected: list[DatasetSpec] = []
        for spec in self._dataset_specs_for_current_tab():
            checker = self.dataset_checks.get(spec.dataset_id)
            if checker is not None and bool(checker.get()):
                selected.append(spec)
        return selected

    def _set_all_datasets_for_current_tab(self, checked: bool):
        for spec in self._dataset_specs_for_current_tab():
            checker = self.dataset_checks.get(spec.dataset_id)
            if checker is not None:
                checker.set(bool(checked))

    def _dataset_info_text(self, spec: DatasetSpec) -> str:
        dataset_dir = dataset_dir_for_spec(spec)
        meta = read_dataset_meta(dataset_dir)
        size_bytes = int(meta.get("storage_size_bytes") or spec.estimated_size_bytes or 0)
        graph_count = int(meta.get("graph_file_count") or spec.estimated_graph_files or 0)
        pair_count = int(meta.get("pair_count") or spec.estimated_pair_count or 0)
        lines = [
            f"Dataset: {spec.name}",
            f"Source: {spec.source}",
            f"Format: {spec.raw_format}",
            f"Storage size: {format_bytes_human(size_bytes)}",
            f"Graph files: {graph_count}",
            f"Pattern/target pairs: {pair_count}",
            "",
            spec.description,
        ]
        if spec.source_url:
            lines.extend(["", f"URL: {spec.source_url}"])
        return "\n".join(lines)

    def _show_dataset_info(self, spec: DatasetSpec):
        messagebox.showinfo(f"{APP_TITLE} - Dataset Info", self._dataset_info_text(spec))

    def _refresh_dataset_rows(self):
        rows_frame = self.datasets_rows_frame
        if rows_frame is None:
            return
        for child in list(rows_frame.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass

        headers = ["Use", "Dataset", "Raw Downloaded", "Converted Ready", "Action", "Info"]
        for col, header in enumerate(headers):
            ttk.Label(rows_frame, text=header, font=("Segoe UI", 9, "bold")).grid(
                row=0,
                column=col,
                padx=(4, 10),
                pady=(0, 6),
                sticky="w",
            )

        specs = self._dataset_specs_for_current_tab()
        if not specs:
            ttk.Label(rows_frame, text="No datasets in catalog for this algorithm tab.").grid(
                row=1,
                column=0,
                columnspan=6,
                sticky="w",
                padx=4,
                pady=(0, 6),
            )
            return

        for row_idx, spec in enumerate(specs, start=1):
            checker = self.dataset_checks.setdefault(spec.dataset_id, tk.BooleanVar(value=False))
            dataset_dir = dataset_dir_for_spec(spec)
            meta = read_dataset_meta(dataset_dir)
            raw_ready = bool(meta.get("raw_ready", False))
            converted_ready = bool(meta.get("converted_ready", False))
            in_progress = bool(self.dataset_download_jobs.get(spec.dataset_id, False))
            download_kind = _dataset_download_kind(spec)

            ttk.Checkbutton(rows_frame, variable=checker).grid(row=row_idx, column=0, padx=(4, 8), pady=(0, 4), sticky="w")
            ttk.Label(rows_frame, text=spec.name).grid(row=row_idx, column=1, padx=(4, 8), pady=(0, 4), sticky="w")
            ttk.Label(rows_frame, text="Yes" if raw_ready else "No").grid(row=row_idx, column=2, padx=(4, 8), pady=(0, 4), sticky="w")
            ttk.Label(rows_frame, text="Yes" if converted_ready else "No").grid(row=row_idx, column=3, padx=(4, 8), pady=(0, 4), sticky="w")

            action_text = "Download"
            action_state = tk.NORMAL
            action_command = lambda sid=spec.dataset_id: self._start_dataset_download(sid)
            if in_progress:
                action_text = "Working..."
                action_state = tk.DISABLED
            elif download_kind == "manual_request":
                action_text = "Request"
                action_state = tk.NORMAL
                action_command = lambda sid=spec.dataset_id: self._request_dataset_access(sid)
            elif raw_ready:
                action_text = "Downloaded"
                action_state = tk.DISABLED

            ttk.Button(
                rows_frame,
                text=action_text,
                state=action_state,
                command=action_command,
                width=12,
            ).grid(row=row_idx, column=4, padx=(4, 8), pady=(0, 4), sticky="w")
            ttk.Button(
                rows_frame,
                text="i",
                command=lambda s=spec: self._show_dataset_info(s),
                width=2,
            ).grid(row=row_idx, column=5, padx=(0, 8), pady=(0, 4), sticky="w")

    def _download_selected_datasets(self):
        selected = self._selected_dataset_specs_for_current_tab()
        if not selected:
            messagebox.showwarning(APP_TITLE, "Select one or more datasets in the Datasets tab.")
            return
        for spec in selected:
            if _dataset_download_kind(spec) == "manual_request":
                self._request_dataset_access(spec.dataset_id)
            elif dataset_raw_ready(spec):
                continue
            else:
                self._start_dataset_download(spec.dataset_id)

    def _request_dataset_access(self, dataset_id: str):
        spec = self.dataset_spec_by_id.get(str(dataset_id).strip().lower())
        if spec is None:
            return
        dataset_dir = dataset_dir_for_spec(spec)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        request_url = str(dict(spec.download or {}).get("request_url") or spec.source_url or "").strip()
        raw_ready = _raw_dataset_has_files(dataset_dir)
        payload = {
            "dataset_id": spec.dataset_id,
            "name": spec.name,
            "tab_id": spec.tab_id,
            "source": spec.source,
            "source_url": spec.source_url,
            "raw_format": spec.raw_format,
            "description": spec.description,
            "raw_ready": bool(raw_ready),
            "converted_ready": False,
            "source_kind": "manual_request",
            "inputs": {},
            "request_url": request_url,
            "note": str(dict(spec.prepare or {}).get("note") or "Dataset requires manual request/import.").strip(),
            "storage_size_bytes": int(_dir_total_size_bytes(dataset_dir)),
            "graph_file_count": int(max(0, int(spec.estimated_graph_files or 0))),
            "pair_count": int(max(0, int(spec.estimated_pair_count or 0))),
        }
        write_dataset_meta(dataset_dir, payload)
        if request_url:
            try:
                webbrowser.open(request_url)
            except Exception:
                pass
        self._append_log(
            f"Manual-request dataset: {spec.name} | raw_dir={str((dataset_dir / 'raw').resolve())}",
            level="notice",
        )
        self._refresh_dataset_rows()
        if request_url:
            messagebox.showinfo(
                APP_TITLE,
                f"Opened request page for '{spec.name}'.\n\n"
                f"After access is granted, place raw files under:\n{str((dataset_dir / 'raw').resolve())}",
            )
        else:
            messagebox.showinfo(
                APP_TITLE,
                f"'{spec.name}' requires manual access/import.\n\n"
                f"Place raw files under:\n{str((dataset_dir / 'raw').resolve())}",
            )

    def _start_dataset_download(self, dataset_id: str):
        spec = self.dataset_spec_by_id.get(str(dataset_id).strip().lower())
        if spec is None:
            return
        if _dataset_download_kind(spec) == "manual_request":
            self._request_dataset_access(spec.dataset_id)
            return
        if self.dataset_download_jobs.get(spec.dataset_id, False):
            return
        self.dataset_download_jobs[spec.dataset_id] = True
        self._refresh_dataset_rows()
        self._append_log(f"Dataset job started: {spec.name}", level="notice")

        def _worker():
            error_text = None
            try:
                payload = prepare_dataset(spec)
                size_text = format_bytes_human(int(payload.get("storage_size_bytes") or 0))
                graphs = int(payload.get("graph_file_count") or 0)
                pairs = int(payload.get("pair_count") or 0)
                self._append_log_threadsafe(
                    f"Dataset ready: {spec.name} | size={size_text} graphs={graphs} pairs={pairs}",
                    level="success",
                )
            except Exception as exc:
                error_text = str(exc)
                self._append_log_threadsafe(f"Dataset job failed for {spec.name}: {exc}", level="error")
            finally:
                def _finish():
                    self.dataset_download_jobs[spec.dataset_id] = False
                    self._refresh_dataset_rows()
                    if error_text:
                        messagebox.showerror(APP_TITLE, f"Dataset processing failed for '{spec.name}':\n{error_text}")
                self.after(0, _finish)

        threading.Thread(target=_worker, daemon=True).start()

    def _build_variant_section(self, parent: ttk.Frame, tab_id: str):
        container = ttk.Frame(parent, padding=8)
        container.pack(fill=tk.X)
        ttk.Label(container, text="Check one or more variants in this tab, or use Check All.").pack(fill=tk.X, pady=(0, 6))
        tools = ttk.Frame(container)
        tools.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(tools, text="Check All", command=lambda t=tab_id: self._set_all_variants(t, True)).pack(side=tk.LEFT)
        ttk.Button(tools, text="Clear All", command=lambda t=tab_id: self._set_all_variants(t, False)).pack(side=tk.LEFT, padx=(8, 0))

        table_wrap = ttk.Frame(container)
        table_wrap.pack(fill=tk.X, expand=True)
        vars_canvas = tk.Canvas(
            table_wrap,
            highlightthickness=0,
            height=1,
            bg=self._theme_palette().get("panel_bg", self._theme_palette().get("bg", "#FFFFFF")),
        )
        vars_x_scroll = ttk.Scrollbar(table_wrap, orient=tk.HORIZONTAL, command=vars_canvas.xview)
        vars_canvas.configure(xscrollcommand=vars_x_scroll.set)
        vars_canvas.pack(side=tk.TOP, fill=tk.X, expand=True)
        vars_frame = ttk.Frame(vars_canvas)
        vars_canvas.create_window((0, 0), window=vars_frame, anchor="nw")
        variants = [v for v in SOLVER_VARIANTS if v.tab_id == tab_id]
        if not variants:
            return

        families = list(dict.fromkeys(v.family for v in variants))

        family_label_prefix = {
            "vf3": "VF3",
            "glasgow": "Glasgow",
            "dijkstra": "Dijkstra",
            "sp_via": "With Intermediate",
            "dial": "Dial",
        }

        def role_key_and_label(variant: SolverVariant) -> tuple[str, str]:
            label = str(variant.label or "").strip()
            lower_label = label.lower()
            if (
                str(variant.role or "").strip().lower() == "baseline"
                or "baseline" in lower_label
                or str(variant.variant_id).strip().lower().endswith("_baseline")
            ):
                return "baseline", "Benchmark"

            prefix = family_label_prefix.get(str(variant.family or "").strip().lower(), "")
            role_text = label
            if prefix:
                prefix_space = f"{prefix} "
                if label.lower().startswith(prefix_space.lower()):
                    role_text = label[len(prefix_space):].strip()

            if not role_text:
                parts = str(variant.variant_id or "").split("_", 1)
                role_text = parts[1].replace("_", " ").strip() if len(parts) > 1 else str(variant.variant_id or "").strip()
            if not role_text:
                role_text = "Unknown"
            return role_text.lower(), role_text

        def family_label(family: str) -> str:
            f = str(family or "").strip().lower()
            if f == "vf3":
                return "VF3 (.grf)"
            if f == "glasgow":
                return "Glasgow (.lad)"
            if f == "dijkstra":
                return "Dijkstra (.csv)"
            if f == "dial":
                return "Dial (.csv)"
            if f == "sp_via":
                return "With Intermediate (.csv)"
            return f.title()

        role_display: dict[str, str] = {}
        by_family_role: dict[tuple[str, str], SolverVariant] = {}
        for variant in variants:
            key, display = role_key_and_label(variant)
            role_display.setdefault(key, display)
            by_family_role[(variant.family, key)] = variant

        role_keys = sorted(role_display.keys(), key=lambda r: (0 if r == "baseline" else 1, role_display.get(r, r).lower()))

        ttk.Label(vars_frame, text="Family", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, padx=(0, 8), pady=(0, 6), sticky="w")
        for col, role in enumerate(role_keys, start=1):
            ttk.Label(vars_frame, text=role_display.get(role, role), font=("Segoe UI", 9, "bold")).grid(row=0, column=col, padx=(0, 12), pady=(0, 6), sticky="w")

        for row, family in enumerate(families, start=1):
            ttk.Label(vars_frame, text=family_label(family)).grid(row=row, column=0, padx=(0, 8), pady=(0, 6), sticky="w")
            for col, role in enumerate(role_keys, start=1):
                variant = by_family_role.get((family, role))
                if variant is None:
                    tk.Label(vars_frame, text="-", fg="#888888").grid(row=row, column=col, padx=(0, 12), pady=(0, 6), sticky="w")
                    continue
                cb = ttk.Checkbutton(
                    vars_frame,
                    text="",
                    variable=self.variant_checks[variant.variant_id],
                    command=self._on_variants_changed,
                )
                cb.grid(row=row, column=col, padx=(0, 12), pady=(0, 6), sticky="w")

        def _refresh_variant_scrollbar(_evt=None):
            try:
                vars_canvas.configure(scrollregion=vars_canvas.bbox("all"))
                req_w = max(1, int(vars_frame.winfo_reqwidth()))
                req_h = max(1, int(vars_frame.winfo_reqheight()))
                canvas_w = max(1, int(vars_canvas.winfo_width()))
                vars_canvas.configure(height=req_h + 2)
                if req_w > canvas_w + 2:
                    if not vars_x_scroll.winfo_manager():
                        vars_x_scroll.pack(side=tk.TOP, fill=tk.X)
                else:
                    if vars_x_scroll.winfo_manager():
                        vars_x_scroll.pack_forget()
                    vars_canvas.xview_moveto(0.0)
            except Exception:
                pass

        vars_frame.bind("<Configure>", _refresh_variant_scrollbar)
        vars_canvas.bind("<Configure>", _refresh_variant_scrollbar)
        self.after(0, _refresh_variant_scrollbar)

    def _set_all_variants(self, tab_id: str, checked: bool):
        for variant in SOLVER_VARIANTS:
            if variant.tab_id == tab_id:
                self.variant_checks[variant.variant_id].set(checked)
        self._on_variants_changed()

    def _on_variants_changed(self):
        self._refresh_3d_variant_choices()

    def _on_tab_changed(self):
        tab_index = self.main_tab.index(self.main_tab.select())
        self.tab_id_var.set("subgraph" if tab_index == 0 else "shortest_path")
        self._on_run_mode_changed()
        self._on_variable_selection_changed()
        self._on_parallel_settings_changed()
        self._refresh_3d_variant_choices()
        self._refresh_dataset_rows()

    def _on_run_mode_changed(self):
        run_mode = self.run_mode_var.get().strip().lower()
        timed_mode = run_mode == "timed"
        self.time_limit_entry.configure(state=tk.NORMAL if timed_mode else tk.DISABLED)
        self._on_variable_selection_changed()

    def _on_parallel_settings_changed(self):
        supported = self.detected_logical_cores > 1
        if not supported:
            self.parallel_enabled_var.set(False)
        try:
            self.parallel_check.configure(state=tk.NORMAL if supported else tk.DISABLED)
            entry_enabled = supported and bool(self.parallel_enabled_var.get())
            self.parallel_workers_entry.configure(state=tk.NORMAL if entry_enabled else tk.DISABLED)
        except Exception:
            pass

    def _on_outlier_filter_changed(self):
        if not hasattr(self, "outlier_filter_blurb"):
            return
        mode = self.outlier_filter_var.get().strip().lower()
        blurb_text = ""
        if mode == "mad":
            blurb_text = (
                "MAD (3-sigma): centers on the median, estimates spread from median absolute deviation, "
                f"and drops samples beyond 3 x 1.4826 x MAD (requires >= {DEFAULT_OUTLIER_MIN_SAMPLES} samples)."
            )
        elif mode == "iqr":
            blurb_text = (
                "IQR (1.5x): computes Q1/Q3 and drops samples outside [Q1 - 1.5xIQR, Q3 + 1.5xIQR] "
                f"(requires >= {DEFAULT_OUTLIER_MIN_SAMPLES} samples)."
            )

        try:
            if blurb_text:
                self.outlier_filter_blurb.configure(text=blurb_text)
                self._refresh_outlier_blurb_wraplength()
                self.outlier_filter_blurb.grid(row=9, column=0, columnspan=2, pady=(4, 0), sticky="ew")
            else:
                self.outlier_filter_blurb.grid_forget()
        except Exception:
            pass

    def _refresh_outlier_blurb_wraplength(self):
        if not hasattr(self, "outlier_filter_blurb"):
            return
        try:
            parent = self.outlier_filter_blurb.nametowidget(self.outlier_filter_blurb.winfo_parent())
            width = int(parent.winfo_width() or parent.winfo_reqwidth() or 260)
            wrap = max(180, width - 16)
            self.outlier_filter_blurb.configure(wraplength=wrap)
        except Exception:
            pass

    def _on_outlier_blurb_parent_resize(self, _event=None):
        self._refresh_outlier_blurb_wraplength()

    def _refresh_stats_blurb_wraplength(self, _event=None):
        wrap_parent = self.stats_wrap
        if wrap_parent is None:
            return
        try:
            width = int(wrap_parent.winfo_width() or wrap_parent.winfo_reqwidth() or 800)
            wrap = max(260, width - 24)
            if self.stats_blurb_label is not None:
                self.stats_blurb_label.configure(wraplength=wrap)
            if self.stats_summary_label is not None:
                self.stats_summary_label.configure(wraplength=wrap)
        except Exception:
            pass

    def _on_variable_selection_changed(self):
        tab_id = self.tab_id_var.get()
        run_mode = self.run_mode_var.get().strip().lower()
        timed_mode = run_mode == "timed"
        valid_ids = ["n", "density"] if tab_id == "shortest_path" else ["n", "density", "k"]

        if "k" not in valid_ids:
            self.var_selected["k"].set(False)
        if not any(self.var_selected[var_id].get() for var_id in valid_ids):
            self.var_selected["n"].set(True)

        for var_id, widgets in self.sweep_rows.items():
            is_allowed = var_id in valid_ids
            is_selected = self.var_selected[var_id].get() if is_allowed else False
            widgets["use_cb"].configure(state=tk.NORMAL if is_allowed else tk.DISABLED)
            widgets["start"].configure(state=tk.NORMAL if is_allowed else tk.DISABLED)
            widgets["end"].configure(state=tk.NORMAL if (is_allowed and is_selected and (not timed_mode)) else tk.DISABLED)
            widgets["step"].configure(state=tk.NORMAL if (is_allowed and is_selected) else tk.DISABLED)
        k_label = self.sweep_rows.get("k", {}).get("label")
        if k_label is not None:
            label_text = "K (nodes)" if self.k_mode_var.get().strip().lower() == "absolute" else "k % of N"
            try:
                k_label.configure(text=label_text)
            except Exception:
                pass
        try:
            self.k_mode_combo.configure(state=tk.NORMAL if tab_id == "subgraph" else tk.DISABLED)
        except Exception:
            pass

    def _refresh_3d_variant_choices(self):
        selected = self._selected_variants_for_current_tab()
        labels = [variant.label for variant in selected]
        self.variant_combo["values"] = labels
        if labels:
            current = self.plot3d_variant_var.get().strip()
            if current not in labels:
                self.plot3d_variant_var.set(labels[0])
        else:
            self.plot3d_variant_var.set("")

    def _apply_log_line_style(self, start_idx: str, end_idx: str, level: str):
        level_key = str(level or "info").strip().lower()
        if level_key not in LOG_COLOR_TAGS:
            level_key = "info"
        for tag_name in LOG_COLOR_TAGS:
            try:
                self.log_box.tag_remove(tag_name, start_idx, end_idx)
            except Exception:
                pass
        try:
            self.log_box.tag_add(level_key, start_idx, end_idx)
        except Exception:
            pass

    def _append_log(self, text: str, level: str = "info"):
        self.log_box.configure(state=tk.NORMAL)
        auto_follow = self._log_should_autoscroll()
        insert_at = self._first_live_log_index_locked()
        if insert_at is None:
            insert_at = tk.END
        start_idx = self.log_box.index(insert_at)
        line_text = text + "\n"
        self.log_box.insert(start_idx, line_text)
        end_idx = self.log_box.index(f"{start_idx}+{len(line_text)}c")
        self._apply_log_line_style(start_idx, end_idx, level)
        if auto_follow:
            self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def _append_log_threadsafe(self, text: str, level: str = "info"):
        self.after(0, lambda: self._append_log(text, level=level))

    def _clear_live_log_line_locked(self, token: str | None = None):
        if token is None:
            tokens = list(self.live_log_lines.keys())
        else:
            if token not in self.live_log_lines:
                return
            tokens = [token]
        for tok in tokens:
            mark_name = self.live_log_lines.pop(tok, None)
            if not mark_name:
                continue
            try:
                idx = self.log_box.index(mark_name)
                self.log_box.delete(idx, f"{idx} lineend+1c")
            except Exception:
                pass
            try:
                self.log_box.mark_unset(mark_name)
            except Exception:
                pass

    def _first_live_log_index_locked(self):
        best_idx = None
        best_key = None
        for token, mark_name in self.live_log_lines.items():
            try:
                idx = self.log_box.index(mark_name)
                line_str, col_str = idx.split(".", 1)
                key = (int(line_str), int(col_str))
            except Exception:
                continue
            if best_key is None or key < best_key:
                best_key = key
                best_idx = idx
        return best_idx

    def _log_should_autoscroll(self):
        try:
            _start, end = self.log_box.yview()
            return float(end) >= 0.995
        except Exception:
            return True

    def _set_live_log_line(self, token: str, text: str, level: str = "notice"):
        self.log_box.configure(state=tk.NORMAL)
        auto_follow = self._log_should_autoscroll()
        try:
            mark_name = self.live_log_lines.get(token)
            if mark_name is None:
                last_idx = self.log_box.index("end-1c")
                if last_idx != "1.0":
                    prev_char = self.log_box.get("end-2c", "end-1c")
                    if prev_char != "\n":
                        self.log_box.insert(tk.END, "\n")
                mark_name = f"live_log_{len(self.live_log_lines) + 1}_{int(time.perf_counter_ns())}"
                self.live_log_lines[token] = mark_name
                self.log_box.mark_set(mark_name, "end-1c")
                self.log_box.mark_gravity(mark_name, tk.LEFT)
            else:
                try:
                    idx = self.log_box.index(mark_name)
                    self.log_box.delete(idx, f"{idx} lineend+1c")
                except Exception:
                    try:
                        self.log_box.mark_unset(mark_name)
                    except Exception:
                        pass
                    mark_name = f"live_log_{len(self.live_log_lines) + 1}_{int(time.perf_counter_ns())}"
                    self.live_log_lines[token] = mark_name
                    self.log_box.mark_set(mark_name, "end-1c")
                    self.log_box.mark_gravity(mark_name, tk.LEFT)
            start_idx = self.log_box.index(mark_name)
            line_text = text + "\n"
            self.log_box.insert(start_idx, line_text)
            end_idx = self.log_box.index(f"{start_idx}+{len(line_text)}c")
            self._apply_log_line_style(start_idx, end_idx, level)
            if auto_follow:
                self.log_box.see(tk.END)
        finally:
            self.log_box.configure(state=tk.DISABLED)

    def _set_live_log_line_threadsafe(self, token: str, text: str, level: str = "notice"):
        self.after(0, lambda: self._set_live_log_line(token, text, level=level))

    def _clear_live_log_line_threadsafe(self, token: str | None = None):
        self.after(0, lambda: self._clear_live_log_line(token=token))

    def _clear_live_log_line(self, token: str | None = None):
        self.log_box.configure(state=tk.NORMAL)
        try:
            self._clear_live_log_line_locked(token=token)
        finally:
            self.log_box.configure(state=tk.DISABLED)

    def _set_run_timer_visible(self, visible: bool):
        if visible:
            if not self.run_log_timer_label.winfo_ismapped():
                self.run_log_timer_label.pack(side=tk.RIGHT)
        else:
            if self.run_log_timer_label.winfo_ismapped():
                self.run_log_timer_label.pack_forget()

    def _format_hms(self, total_seconds: int) -> str:
        total_seconds = max(0, int(total_seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _refresh_run_timer_label(self):
        if self.run_timer_deadline_monotonic is None:
            return
        remaining = max(0, int(self.run_timer_deadline_monotonic - time.monotonic()))
        self.run_log_timer_label.configure(text=f"Time Left: {self._format_hms(remaining)}")
        self.run_timer_after_id = self.after(1000, self._refresh_run_timer_label)

    def _stop_run_timer(self, hide: bool = True):
        if self.run_timer_after_id is not None:
            try:
                self.after_cancel(self.run_timer_after_id)
            except Exception:
                pass
        self.run_timer_after_id = None
        self.run_timer_deadline_monotonic = None
        if hide:
            self.run_log_timer_label.configure(text="")
            self._set_run_timer_visible(False)

    def _deactivate_visualizer_autoplay(self, reset_last_key: bool = False):
        self._stop_visualizer_autoplay_timer()
        for key in self.visualizer_autoplay_active:
            self.visualizer_autoplay_active[key] = False
        self.visualizer_autoplay_current_key = None
        self.visualizer_autoplay_cycle_start_index = None
        self.visualizer_autoplay_cycle_steps = 0
        if reset_last_key:
            self.visualizer_autoplay_last_key = None
        self._update_visualizer_autoplay_controls()

    def _start_run_timer(self, time_limit_minutes: float | None):
        self._stop_run_timer(hide=False)
        if time_limit_minutes is None:
            self.run_log_timer_label.configure(text="")
            self._set_run_timer_visible(False)
            return None
        self.run_timer_deadline_monotonic = time.monotonic() + (max(0.0, float(time_limit_minutes)) * 60.0)
        self._set_run_timer_visible(True)
        self._refresh_run_timer_label()
        return self.run_timer_deadline_monotonic

    def _clear_run_log(self):
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.live_log_lines = {}
        self.log_box.configure(state=tk.DISABLED)

    def _visualizer_cache_root(self) -> Path | None:
        if not self.session_output_dir:
            return None
        return self.session_output_dir / "visualizer_cache"

    def _flush_visualizer_caches(self, delete_disk: bool = True):
        try:
            self._close_visualizer_fullscreen_popup()
        except Exception:
            pass
        with self.visualizer_cache_lock:
            self.visualizer_bundle_cache_mem.clear()
            self.visualizer_active_context_key = None
            self.visualizer_prefetch_context_key = None
            self.visualizer_prefetch_center_index = None
        self._deactivate_visualizer_autoplay(reset_last_key=True)
        if delete_disk:
            root = self._visualizer_cache_root()
            if root is not None and root.exists():
                try:
                    shutil.rmtree(root, ignore_errors=True)
                except Exception:
                    pass

    def _on_app_close(self):
        self._close_stats_help_popup()
        self._flush_visualizer_caches(delete_disk=True)
        try:
            self.destroy()
        except Exception:
            pass

    def _clear_graphs(self, announce: bool = False):
        had_graphs = any([
            self.runtime_canvas is not None,
            self.memory_canvas is not None,
            self.runtime_3d_canvas is not None,
            self.memory_3d_canvas is not None,
            self.visualizer_graph_canvas is not None,
            self.last_runtime_fig is not None,
            self.last_memory_fig is not None,
            self.last_runtime_3d_fig is not None,
            self.last_memory_3d_fig is not None,
            self.visualizer_graph_fig is not None,
        ])
        self._deactivate_visualizer_autoplay()

        for canvas_attr in ("runtime_canvas", "memory_canvas", "runtime_3d_canvas", "memory_3d_canvas"):
            canvas = getattr(self, canvas_attr)
            if canvas is not None:
                try:
                    canvas.get_tk_widget().destroy()
                except Exception:
                    pass
                setattr(self, canvas_attr, None)

        for fig_attr in ("last_runtime_fig", "last_memory_fig", "last_runtime_3d_fig", "last_memory_3d_fig"):
            fig = getattr(self, fig_attr)
            if fig is not None:
                try:
                    fig.clear()
                except Exception:
                    pass
                setattr(self, fig_attr, None)
        self._clear_visualizer_render()

        self._clear_drilldown()
        self._close_stats_help_popup()
        self._clear_stats_table()
        self.last_plot_context = None
        if announce and had_graphs:
            self._append_log("Graphs cleared.", level="notice")

    def _clear_drilldown(self):
        popup = self.drilldown_popup
        self.drilldown_popup = None
        self.drilldown_popup_mode = None
        self.drilldown_popup_point_key = None
        if popup is not None:
            try:
                popup.destroy()
            except Exception:
                pass
        if self.drilldown_highlight_artist is not None:
            try:
                self.drilldown_highlight_artist.remove()
            except Exception:
                pass
            self.drilldown_highlight_artist = None
            if self.drilldown_highlight_canvas is not None:
                try:
                    self.drilldown_highlight_canvas.draw_idle()
                except Exception:
                    pass
        self.drilldown_highlight_canvas = None

    def _drilldown_point_key(self, metric: str, row: dict):
        return (
            metric,
            str(row.get("variant_id", "")),
            float(row.get("x_value", 0.0)) if row.get("x_value") is not None else None,
            float(row.get("y_value", 0.0)) if row.get("y_value") is not None else None,
        )

    def _drilldown_text_for_row(self, row: dict, metric: str):
        x_val = row.get("x_value")
        y_val = row.get("y_value")
        runtime_samples = list(row.get("runtime_samples_ms") or [])
        memory_samples = list(row.get("memory_samples_kb") or [])
        runtime_samples_raw = list(row.get("runtime_samples_raw_ms") or runtime_samples)
        memory_samples_raw = list(row.get("memory_samples_raw_kb") or memory_samples)
        outlier_mode = str(row.get("outlier_filter_mode", "none")).strip().lower()
        outlier_min_samples = row.get("outlier_filter_min_samples", DEFAULT_OUTLIER_MIN_SAMPLES)
        seeds = list(row.get("seeds") or [])
        lines = [
            "Datapoint Drilldown",
            f"Metric: {metric}",
            f"Variant: {row.get('variant_label', row.get('variant_id', 'unknown'))}",
            f"X value: {number_or_blank(x_val) if x_val is not None else 'n/a'}",
            f"Y value: {number_or_blank(y_val) if y_val is not None else 'n/a'}",
            f"Outlier filter: {outlier_mode} (min samples={outlier_min_samples})",
            "",
            f"Runtime median (ms): {number_or_blank(row.get('runtime_median_ms'))}",
            f"Runtime stdev (ms): {number_or_blank(row.get('runtime_stdev_ms'))}",
            f"Runtime samples used/total: {len(runtime_samples)}/{len(runtime_samples_raw)}",
            f"Runtime samples used: {json.dumps(runtime_samples)}",
            f"Runtime samples raw: {json.dumps(runtime_samples_raw)}",
            "",
            f"Memory median (KiB): {number_or_blank(row.get('memory_median_kb'))}",
            f"Memory stdev (KiB): {number_or_blank(row.get('memory_stdev_kb'))}",
            f"Memory samples used/total: {len(memory_samples)}/{len(memory_samples_raw)}",
            f"Memory samples used: {json.dumps(memory_samples)}",
            f"Memory samples raw: {json.dumps(memory_samples_raw)}",
            "",
            f"Completed iterations: {row.get('completed_iterations')}/{row.get('requested_iterations')}",
            f"Seeds: {json.dumps(seeds)}",
        ]
        return "\n".join(lines)

    def _set_drilldown_highlight(self, ax, canvas: FigureCanvasTkAgg, x_value: float, y_value: float):
        if self.drilldown_highlight_artist is not None:
            try:
                self.drilldown_highlight_artist.remove()
            except Exception:
                pass
        self.drilldown_highlight_artist = ax.plot(
            [x_value],
            [y_value],
            marker="o",
            markersize=12,
            markerfacecolor="none",
            markeredgecolor="#d7263d",
            markeredgewidth=2.0,
            linestyle="None",
            zorder=1000,
        )[0]
        self.drilldown_highlight_canvas = canvas
        try:
            canvas.draw_idle()
        except Exception:
            pass

    def _open_output_dir(self):
        if not self.session_output_dir:
            return
        try:
            target = str(self.session_output_dir)
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", target], check=True)
            else:
                subprocess.run(["xdg-open", target], check=True)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Failed to open folder:\n{exc}")

    def _save_exports_again(self):
        if not self.last_run_payload or not self.session_output_dir:
            return
        try:
            self._save_exports(self.last_run_payload, self.session_output_dir)
            messagebox.showinfo(APP_TITLE, f"Exports updated in:\n{self.session_output_dir}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Failed to save exports:\n{exc}")

    def _build_headless_manifest_from_config(self, config: dict) -> dict:
        run_mode = str(config.get("run_mode") or "threshold").strip().lower()
        if run_mode != "threshold":
            raise ValueError("Timed GUI runs cannot be exported as a reproducible headless manifest. Switch Stop Mode to Threshold first.")

        input_mode = str(config.get("input_mode") or "independent").strip().lower()
        manifest: dict[str, object] = {
            "schema_version": "capstone-benchmark-manifest-v1",
            "preset": "standard",
            "tab_id": str(config.get("tab_id") or "").strip().lower(),
            "input_mode": input_mode,
            "graph_family": str(config.get("graph_family") or "random_density").strip().lower() or "random_density",
            "selected_variants": [str(item).strip().lower() for item in list(config.get("selected_variants") or []) if str(item).strip()],
            "selected_datasets": [str(item).strip().lower() for item in list(config.get("selected_datasets") or []) if str(item).strip()],
            "k_mode": str(config.get("k_mode") or "absolute").strip().lower() or "absolute",
            "prepare_datasets": True,
            "iterations": int(config.get("iterations") or 1),
            "base_seed": int(config.get("base_seed") or 1),
            "timeout_as_missing": bool(config.get("timeout_as_missing", True)),
            "delete_generated_inputs": bool(config.get("delete_generated_inputs", True)),
        }
        solver_timeout = config.get("solver_timeout_seconds")
        if solver_timeout not in {None, ""}:
            manifest["solver_timeout_seconds"] = float(solver_timeout)
        failure_policy = str(config.get("failure_policy") or "").strip().lower()
        if failure_policy:
            manifest["failure_policy"] = failure_policy
        retry_failed_trials = config.get("retry_failed_trials")
        if retry_failed_trials is not None:
            manifest["retry_failed_trials"] = int(retry_failed_trials)
        outlier_filter = str(config.get("outlier_filter") or "").strip().lower()
        if outlier_filter:
            manifest["outlier_filter"] = outlier_filter

        if input_mode == "independent":
            values: dict[str, list[float]] = {}
            fixed_values = dict(config.get("fixed_values") or {})
            var_ranges = dict(config.get("var_ranges") or {})
            value_keys = ["n", "density"] if manifest["tab_id"] == "shortest_path" else ["n", "density", "k"]
            for key in value_keys:
                current = list(var_ranges.get(key) or [])
                if current:
                    values[key] = [float(value) for value in current]
                elif key in fixed_values:
                    values[key] = [float(fixed_values[key])]
            manifest["values"] = values

        return manifest

    def _infer_manifest_range_fields(self, var_id: str, raw_values: object) -> tuple[bool, str, str, str]:
        values = [float(item) for item in list(raw_values or [])]
        if not values:
            raise ValueError(f"Manifest is missing values for '{var_id}'.")
        if len(values) == 1:
            return False, self._format_point_value(var_id, float(values[0])), "", ""

        ordered = [float(item) for item in values]
        step = ordered[1] - ordered[0]
        if abs(step) <= 1e-12:
            raise ValueError(f"Manifest values for '{var_id}' must not repeat.")
        for idx in range(2, len(ordered)):
            delta = ordered[idx] - ordered[idx - 1]
            if abs(delta - step) > 1e-9:
                raise ValueError(
                    f"Manifest values for '{var_id}' are not representable by the GUI sweep controls. "
                    "Only single values or arithmetic progressions can be imported."
                )
        return (
            True,
            self._format_point_value(var_id, float(ordered[0])),
            self._format_point_value(var_id, float(ordered[-1])),
            self._format_point_value(var_id, float(step)),
        )

    def _apply_headless_manifest_to_controls(self, manifest: dict):
        tab_id = str(manifest.get("tab_id") or "").strip().lower()
        if tab_id not in {"subgraph", "shortest_path"}:
            raise ValueError("Manifest requires tab_id=subgraph or tab_id=shortest_path.")

        input_mode = str(manifest.get("input_mode") or "independent").strip().lower()
        if input_mode not in {"independent", "datasets"}:
            raise ValueError("Manifest input_mode must be independent or datasets.")

        self.main_tab.select(0 if tab_id == "subgraph" else 1)
        self._on_tab_changed()

        self.input_source_tabs.select(0 if input_mode == "independent" else 1)
        self._on_input_mode_tab_changed()

        for variant in SOLVER_VARIANTS:
            if variant.tab_id == tab_id:
                self.variant_checks[variant.variant_id].set(False)
        selected_variants = [str(item).strip().lower() for item in list(manifest.get("selected_variants") or []) if str(item).strip()]
        for variant_id in selected_variants:
            checker = self.variant_checks.get(variant_id)
            if checker is None:
                raise ValueError(f"Manifest references unknown variant: {variant_id}")
            checker.set(True)
        self._on_variants_changed()

        for spec in self.dataset_specs:
            if spec.tab_id == tab_id:
                self.dataset_checks[spec.dataset_id].set(False)
        selected_datasets = [str(item).strip().lower() for item in list(manifest.get("selected_datasets") or []) if str(item).strip()]
        for dataset_id in selected_datasets:
            checker = self.dataset_checks.get(dataset_id)
            if checker is None:
                raise ValueError(f"Manifest references unknown dataset: {dataset_id}")
            checker.set(True)
        self._refresh_dataset_rows()

        self.iterations_var.set(str(int(manifest.get("iterations") or 1)))
        base_seed = manifest.get("base_seed")
        self.seed_var.set("" if base_seed in {None, ""} else str(int(base_seed)))
        self.run_mode_var.set("threshold")
        self.time_limit_minutes_var.set("10")
        solver_timeout = manifest.get("solver_timeout_seconds")
        self.solver_timeout_seconds_var.set("0" if solver_timeout in {None, ""} else str(float(solver_timeout)))
        self.failure_policy_var.set(str(manifest.get("failure_policy") or "continue").strip().lower() or "continue")
        self.retry_failed_trials_var.set(str(int(manifest.get("retry_failed_trials") or 0)))
        self.timeout_as_missing_var.set(bool(manifest.get("timeout_as_missing", True)))
        self.outlier_filter_var.set(str(manifest.get("outlier_filter") or "none").strip().lower() or "none")
        self.delete_generated_inputs_var.set(bool(manifest.get("delete_generated_inputs", True)))
        self.graph_family_var.set(
            generator_mod.normalize_graph_family(str(manifest.get("graph_family") or "random_density"))
        )
        self.k_mode_var.set(str(manifest.get("k_mode") or "absolute").strip().lower() or "absolute")
        self._on_run_mode_changed()
        self._on_outlier_filter_changed()

        valid_ids = ["n", "density"] if tab_id == "shortest_path" else ["n", "density", "k"]
        for var_id in ["n", "density", "k"]:
            self.var_selected[var_id].set(False)
            self.var_end[var_id].set("")
            self.var_step[var_id].set("1" if var_id != "density" else "0.01")

        if input_mode == "independent":
            values = dict(manifest.get("values") or {})
            for var_id in valid_ids:
                selected, start_value, end_value, step_value = self._infer_manifest_range_fields(var_id, values.get(var_id) or [])
                self.var_selected[var_id].set(selected)
                self.var_start[var_id].set(start_value)
                self.var_end[var_id].set(end_value)
                self.var_step[var_id].set(step_value if step_value else ("1" if var_id != "density" else "0.01"))
        else:
            defaults = {"n": "64", "density": "0.05", "k": "10"}
            for var_id in valid_ids:
                self.var_start[var_id].set(defaults[var_id])
                self.var_end[var_id].set("")
                self.var_step[var_id].set("1" if var_id != "density" else "0.01")

        self._on_variable_selection_changed()
        self._refresh_3d_variant_choices()

    def _export_reproducible_manifest(self):
        try:
            config = self._validate_and_build_config()
            manifest = self._build_headless_manifest_from_config(config)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        target = filedialog.asksaveasfilename(
            title="Export Benchmark Manifest",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not target:
            return

        target_path = Path(target)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps(manifest, indent=2, default=serialize_for_json) + "\n", encoding="utf-8")
            self._append_log(f"Exported reproducible manifest: {target_path}", level="notice")
            messagebox.showinfo(APP_TITLE, f"Manifest written to:\n{target_path}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Failed to export manifest:\n{exc}")

    def _import_reproducible_manifest(self):
        target = filedialog.askopenfilename(
            title="Import Benchmark Manifest",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not target:
            return

        try:
            from desktop_runner import headless_runner as headless_mod

            manifest_path = Path(target)
            manifest = headless_mod.merge_preset_defaults(headless_mod.load_manifest(manifest_path))
            self._apply_headless_manifest_to_controls(manifest)
            self._append_log(f"Imported reproducible manifest: {manifest_path}", level="notice")
            messagebox.showinfo(APP_TITLE, f"Manifest loaded from:\n{manifest_path}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Failed to import manifest:\n{exc}")

    def _selected_variants_for_current_tab(self):
        tab_id = self.tab_id_var.get()
        return [
            variant
            for variant in SOLVER_VARIANTS
            if variant.tab_id == tab_id and self.variant_checks[variant.variant_id].get()
        ]

    def _k_mode(self, config: dict | None = None) -> str:
        if isinstance(config, dict):
            mode = str(config.get("k_mode", "percent")).strip().lower()
        else:
            mode = self.k_mode_var.get().strip().lower()
        return mode if mode in {"percent", "absolute"} else "percent"

    def _axis_label(self, var_id: str, config: dict | None = None) -> str:
        if var_id != "k":
            return axis_label(var_id)
        return "K (nodes)" if self._k_mode(config) == "absolute" else "k % of N"

    def _format_point_value(self, var_id: str, value: float, config: dict | None = None) -> str:
        if var_id != "k":
            return format_point_value(var_id, value)
        if self._k_mode(config) == "absolute":
            return str(int(round(value)))
        return format_point_value(var_id, value)

    def _format_step_value(self, var_id: str, value: float | None, config: dict | None = None) -> str:
        if var_id != "k":
            return format_step_value(var_id, value)
        if value is None:
            return "n/a"
        if self._k_mode(config) == "absolute":
            return str(int(round(value)))
        return format_step_value(var_id, value)

    def _format_run_input_segment(self, config: dict, var_id: str) -> str:
        specs = config.get("input_specs", {})
        spec = specs.get(var_id)
        label = self._axis_label(var_id, config)
        if spec is None:
            return f"{label}=n/a"
        selected = bool(spec.get("selected"))
        start = spec.get("start")
        end = spec.get("end")
        step = spec.get("step")
        if selected:
            if config.get("run_mode") == "timed":
                return (
                    f"{label} start={self._format_point_value(var_id, float(start), config)} "
                    f"step={self._format_step_value(var_id, None if step is None else float(step), config)} (timed)"
                )
            return (
                f"{label} {self._format_point_value(var_id, float(start), config)}->{self._format_point_value(var_id, float(end), config)} "
                f"step={self._format_step_value(var_id, None if step is None else float(step), config)}"
            )
        return f"{label} fixed={self._format_point_value(var_id, float(start), config)}"

    def _shortest_metrics_from_csv(self, path: Path) -> tuple[int, float]:
        nodes: set[str] = set()
        edge_count = 0
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            for raw_line in fh:
                line = str(raw_line or "").strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower().startswith("source,"):
                    continue
                parts = [part.strip() for part in line.split(",")]
                if len(parts) < 2:
                    continue
                src = parts[0]
                dst = parts[1]
                if not src or not dst:
                    continue
                nodes.add(src)
                nodes.add(dst)
                edge_count += 1
        n_nodes = len(nodes)
        density = 0.0
        if n_nodes > 1:
            density = min(1.0, float(edge_count) / float(n_nodes * (n_nodes - 1)))
        return n_nodes, density

    def _resolve_dataset_inputs_for_run(self, point: dict) -> dict[str, Path | str]:
        resolved: dict[str, Path | str] = {}
        raw_inputs = dict(point.get("dataset_inputs") or {})
        for key, value in raw_inputs.items():
            if not isinstance(value, str) or not value.strip():
                continue
            if key == "lad_format":
                resolved[key] = str(value).strip()
            else:
                resolved[str(key)] = Path(value)
        return resolved

    def _build_dataset_mode_config(
        self,
        *,
        tab_id: str,
        selected_variants: list[SolverVariant],
        iterations: int,
        base_seed: int,
        run_mode: str,
        time_limit_minutes: float | None,
        solver_timeout_seconds: float | None,
        failure_policy: str,
        retry_failed_trials: int,
        timeout_as_missing: bool,
        outlier_filter: str,
        k_mode: str,
        style: str,
        variant_for_3d: str | None,
        detected_cores: int,
        parallel_requested: bool,
        requested_workers: int,
        max_workers: int,
    ) -> dict:
        if run_mode != "threshold":
            raise ValueError("Datasets tab currently supports threshold mode only.")

        selected_specs = self._selected_dataset_specs_for_current_tab()
        if not selected_specs:
            raise ValueError("Select at least one dataset in the Datasets tab.")

        missing: list[str] = []
        datapoints: list[dict] = []
        observed_n: list[float] = []
        observed_density: list[float] = []
        for spec in selected_specs:
            if not dataset_converted_ready(spec):
                missing.append(f"{spec.name} (converted files not ready)")
                continue
            inputs = dataset_converted_inputs(spec)
            if not isinstance(inputs, dict):
                missing.append(f"{spec.name} (missing converted input map)")
                continue

            if tab_id == "subgraph":
                needed = ("vf_pattern", "vf_target", "lad_pattern", "lad_target")
                if any(key not in inputs for key in needed):
                    missing.append(f"{spec.name} (missing subgraph converted files)")
                    continue
                for key in needed:
                    if not inputs[key].exists():
                        missing.append(f"{spec.name} ({key} file missing)")
                        break
                else:
                    dataset_dir = dataset_dir_for_spec(spec)
                    meta = read_dataset_meta(dataset_dir)
                    n_nodes = int(meta.get("target_nodes") or 0)
                    k_nodes = int(meta.get("pattern_nodes") or 0)
                    target_edges = int(meta.get("target_edges") or 0)
                    if n_nodes <= 0:
                        target_adj = parse_vf_graph(inputs["vf_target"])
                        n_nodes = len(target_adj)
                        target_edges = count_adj_edges(target_adj)
                    if k_nodes <= 0:
                        pat_adj = parse_vf_graph(inputs["vf_pattern"])
                        k_nodes = len(pat_adj)
                    density = 0.0
                    if n_nodes > 1:
                        density = min(1.0, float(target_edges) / float(n_nodes * (n_nodes - 1)))
                    if n_nodes < 3 or k_nodes < 2 or k_nodes >= n_nodes:
                        missing.append(f"{spec.name} (invalid N/K derived from converted files)")
                        continue
                    k_value = float(k_nodes) if k_mode == "absolute" else float((100.0 * k_nodes) / float(n_nodes))
                    point = {
                        "n": float(n_nodes),
                        "density": float(max(0.000001, density)),
                        "k": float(max(0.000001, min(100.0, k_value))) if k_mode != "absolute" else float(k_nodes),
                        "k_nodes": int(k_nodes),
                        "dataset_id": spec.dataset_id,
                        "dataset_name": spec.name,
                        "dataset_inputs": {k: str(v) for k, v in inputs.items()},
                    }
                    datapoints.append(point)
                    observed_n.append(float(point["n"]))
                    observed_density.append(float(point["density"]))
            else:
                if "dijkstra_file" not in inputs or not inputs["dijkstra_file"].exists():
                    missing.append(f"{spec.name} (missing converted shortest-path CSV)")
                    continue
                dataset_dir = dataset_dir_for_spec(spec)
                meta = read_dataset_meta(dataset_dir)
                n_nodes = int(meta.get("nodes") or 0)
                density = float(meta.get("density") or 0.0)
                if n_nodes < 2:
                    n_nodes, density = self._shortest_metrics_from_csv(inputs["dijkstra_file"])
                if n_nodes < 2:
                    missing.append(f"{spec.name} (converted CSV has fewer than 2 nodes)")
                    continue
                point = {
                    "n": float(n_nodes),
                    "density": float(max(0.000001, min(1.0, density))),
                    "dataset_id": spec.dataset_id,
                    "dataset_name": spec.name,
                    "dataset_inputs": {k: str(v) for k, v in inputs.items()},
                }
                datapoints.append(point)
                observed_n.append(float(point["n"]))
                observed_density.append(float(point["density"]))

        if missing:
            raise ValueError("Dataset readiness check failed:\n" + "\n".join(missing))
        if not datapoints:
            raise ValueError("No runnable datasets selected.")

        var_ranges = {"n": sorted(observed_n), "density": sorted(observed_density)}
        fixed_values = {
            "n": float(datapoints[0]["n"]),
            "density": float(datapoints[0]["density"]),
        }
        input_specs = {
            "n": {"selected": True, "start": float(datapoints[0]["n"]), "end": None, "step": None},
            "density": {"selected": False, "start": float(datapoints[0]["density"]), "end": None, "step": None},
        }
        if tab_id == "subgraph":
            fixed_values["k"] = float(datapoints[0]["k"])
            var_ranges["k"] = sorted({float(point["k"]) for point in datapoints})
            input_specs["k"] = {"selected": False, "start": float(datapoints[0]["k"]), "end": None, "step": None}

        return {
            "tab_id": tab_id,
            "input_mode": "datasets",
            "graph_family": generator_mod.normalize_graph_family(self.graph_family_var.get()),
            "selected_datasets": [spec.dataset_id for spec in selected_specs],
            "selected_variants": [variant.variant_id for variant in selected_variants],
            "selected_variant_labels": {variant.variant_id: variant.label for variant in selected_variants},
            "iterations": iterations,
            "base_seed": base_seed,
            "run_mode": run_mode,
            "time_limit_minutes": time_limit_minutes,
            "solver_timeout_seconds": solver_timeout_seconds,
            "failure_policy": failure_policy,
            "retry_failed_trials": retry_failed_trials,
            "timeout_as_missing": timeout_as_missing,
            "outlier_filter": outlier_filter,
            "k_mode": k_mode,
            "primary_var": "n",
            "secondary_var": None,
            "var_ranges": var_ranges,
            "fixed_values": fixed_values,
            "datapoints": datapoints,
            "timed_start": {},
            "timed_step": {},
            "input_specs": input_specs,
            "plot3d_style": style,
            "plot3d_variant": variant_for_3d,
            "show_stddev_bars": bool(self.show_stddev_var.get()),
            "show_regression_line": bool(self.show_regression_var.get()),
            "show_trendlines_only": bool(self.show_trendlines_only_var.get()),
            "parallel_requested": parallel_requested,
            "requested_workers": requested_workers,
            "max_workers": max_workers,
            "detected_logical_cores": detected_cores,
            "delete_generated_inputs": False,
            "warmup_trials": 0,
        }

    def _validate_and_build_config(self):
        tab_id = self.tab_id_var.get()
        selected_variants = self._selected_variants_for_current_tab()
        if not selected_variants:
            raise ValueError("Select at least one algorithm variant.")

        missing_binaries = []
        for variant in selected_variants:
            path = self.binary_paths.get(variant.variant_id)
            if not path or not path.exists():
                missing_binaries.append(f"{variant.label} -> {path}")
        if missing_binaries:
            raise ValueError("Missing bundled solver binaries:\n" + "\n".join(missing_binaries))

        iterations = parse_int(self.iterations_var.get(), "Iterations per datapoint", minimum=1)
        seed_raw = self.seed_var.get().strip()
        base_seed = random.SystemRandom().randint(1, 2_147_483_647) if seed_raw == "" else parse_int(seed_raw, "Seed", minimum=0)
        detected_cores = int(self.detected_logical_cores)
        parallel_requested = bool(self.parallel_enabled_var.get()) and detected_cores > 1
        requested_workers = parse_int(self.max_workers_var.get(), "Max parallel workers", minimum=1)
        if parallel_requested:
            max_workers = max(1, min(requested_workers, detected_cores))
        else:
            max_workers = 1

        run_mode = self.run_mode_var.get().strip().lower()
        if run_mode not in {"threshold", "timed"}:
            raise ValueError("Stop mode must be threshold or timed.")
        time_limit_minutes = None
        if run_mode == "timed":
            time_limit_minutes = parse_float(self.time_limit_minutes_var.get(), "Time limit (minutes)", minimum=0.01)
        solver_timeout_raw = self.solver_timeout_seconds_var.get().strip()
        solver_timeout_seconds = parse_float(
            solver_timeout_raw if solver_timeout_raw != "" else "0",
            "Solver timeout (seconds)",
            minimum=0.0,
        )
        if solver_timeout_seconds <= 0:
            solver_timeout_seconds = None
        failure_policy = self.failure_policy_var.get().strip().lower()
        if failure_policy not in {"stop", "continue"}:
            raise ValueError("Failure policy must be stop or continue.")
        retry_failed_trials = parse_int(self.retry_failed_trials_var.get(), "Retry failed trials", minimum=0)
        timeout_as_missing = bool(self.timeout_as_missing_var.get())
        outlier_filter = self.outlier_filter_var.get().strip().lower()
        if outlier_filter not in {"none", "mad", "iqr"}:
            raise ValueError("Outlier filter must be none, mad, or iqr.")
        k_mode = self._k_mode()
        input_mode = self._input_mode()

        style = self.plot3d_style_var.get().strip().lower()
        if style not in {"surface", "wireframe", "scatter"}:
            style = "surface"
        selected_variant_label = self.plot3d_variant_var.get().strip()
        variant_lookup = {variant.label: variant.variant_id for variant in selected_variants}
        variant_for_3d = variant_lookup.get(selected_variant_label)
        if not variant_for_3d and selected_variants:
            variant_for_3d = selected_variants[0].variant_id

        if input_mode == "datasets":
            return self._build_dataset_mode_config(
                tab_id=tab_id,
                selected_variants=selected_variants,
                iterations=iterations,
                base_seed=base_seed,
                run_mode=run_mode,
                time_limit_minutes=time_limit_minutes,
                solver_timeout_seconds=solver_timeout_seconds,
                failure_policy=failure_policy,
                retry_failed_trials=retry_failed_trials,
                timeout_as_missing=timeout_as_missing,
                outlier_filter=outlier_filter,
                k_mode=k_mode,
                style=style,
                variant_for_3d=variant_for_3d,
                detected_cores=detected_cores,
                parallel_requested=parallel_requested,
                requested_workers=requested_workers,
                max_workers=max_workers,
            )

        variable_order = ["n", "density", "k"]
        allowed_vars = ["n", "density"] if tab_id == "shortest_path" else variable_order
        selected_vars = [var_id for var_id in allowed_vars if self.var_selected[var_id].get()]
        if not selected_vars:
            raise ValueError("Select at least one independent variable.")
        if len(selected_vars) > 2:
            raise ValueError("At most two independent variables can be selected.")

        var_ranges = {}
        fixed_values = {}
        timed_start = {}
        timed_step = {}
        input_specs = {}
        for var_id in allowed_vars:
            if self.var_selected[var_id].get():
                integer_mode = var_id == "n" or (var_id == "k" and k_mode == "absolute")
                start_raw = self.var_start[var_id].get().strip()
                step_raw = self.var_step[var_id].get().strip()
                end_raw = self.var_end[var_id].get().strip()
                if start_raw == "":
                    raise ValueError(f"Start is required for {self._axis_label(var_id)}.")
                if step_raw == "":
                    raise ValueError(f"Step is required for {self._axis_label(var_id)}.")
                if run_mode != "timed" and end_raw == "":
                    raise ValueError(f"End is required for {self._axis_label(var_id)}.")
                if var_id == "n":
                    start = float(parse_int(start_raw, f"{self._axis_label(var_id)} start", minimum=1))
                    step = float(parse_int(step_raw, f"{self._axis_label(var_id)} step", minimum=1))
                    end = float(parse_int(end_raw, f"{self._axis_label(var_id)} end", minimum=1)) if run_mode != "timed" else start
                elif var_id == "density":
                    start = parse_float(start_raw, f"{self._axis_label(var_id)} start", minimum=0.000001, maximum=1.0)
                    step = parse_float(step_raw, f"{self._axis_label(var_id)} step", minimum=0.000001, maximum=1.0)
                    end = parse_float(end_raw, f"{self._axis_label(var_id)} end", minimum=0.000001, maximum=1.0) if run_mode != "timed" else start
                else:
                    if k_mode == "absolute":
                        start = float(parse_int(start_raw, f"{self._axis_label(var_id)} start", minimum=2))
                        step = float(parse_int(step_raw, f"{self._axis_label(var_id)} step", minimum=1))
                        end = float(parse_int(end_raw, f"{self._axis_label(var_id)} end", minimum=2)) if run_mode != "timed" else start
                    else:
                        start = parse_float(start_raw, f"{self._axis_label(var_id)} start", minimum=0.000001, maximum=100.0)
                        step = parse_float(step_raw, f"{self._axis_label(var_id)} step", minimum=0.000001, maximum=100.0)
                        end = parse_float(end_raw, f"{self._axis_label(var_id)} end", minimum=0.000001, maximum=100.0) if run_mode != "timed" else start
                if run_mode == "timed":
                    timed_start[var_id] = start
                    timed_step[var_id] = step
                    var_ranges[var_id] = []
                    input_specs[var_id] = {
                        "selected": True,
                        "start": float(start),
                        "end": None,
                        "step": float(step),
                    }
                else:
                    values = build_range(start, end, step, integer_mode=integer_mode)
                    if var_id == "density":
                        for v in values:
                            if v <= 0 or v > 1:
                                raise ValueError("Density values must be in (0, 1].")
                    if var_id == "k":
                        if k_mode == "percent":
                            for v in values:
                                if v <= 0 or v > 100:
                                    raise ValueError("k % of N values must be in (0, 100].")
                        else:
                            for v in values:
                                if int(round(v)) < 2:
                                    raise ValueError("K (nodes) values must be >= 2.")
                    var_ranges[var_id] = values
                    input_specs[var_id] = {
                        "selected": True,
                        "start": float(start),
                        "end": float(end),
                        "step": float(step),
                    }
            else:
                start_raw = self.var_start[var_id].get().strip()
                if start_raw == "":
                    raise ValueError(f"Start is required for {self._axis_label(var_id)}.")
                if var_id == "n":
                    fixed_values[var_id] = float(parse_int(start_raw, f"{self._axis_label(var_id)} start", minimum=1))
                elif var_id == "density":
                    fixed_values[var_id] = parse_float(start_raw, f"{self._axis_label(var_id)} start", minimum=0.000001, maximum=1.0)
                else:
                    if k_mode == "absolute":
                        fixed_values[var_id] = float(parse_int(start_raw, f"{self._axis_label(var_id)} start", minimum=2))
                    else:
                        fixed_values[var_id] = parse_float(start_raw, f"{self._axis_label(var_id)} start", minimum=0.000001, maximum=100.0)
                input_specs[var_id] = {
                    "selected": False,
                    "start": float(fixed_values[var_id]),
                    "end": None,
                    "step": None,
                }

        if tab_id in {"subgraph", "shortest_path"}:
            if "n" not in var_ranges:
                n_ref = fixed_values.get("n")
            elif run_mode == "timed":
                n_ref = timed_start.get("n")
            else:
                n_ref = min(var_ranges["n"])
            if n_ref is not None and int(round(n_ref)) < 2:
                if tab_id == "subgraph":
                    raise ValueError("N must be at least 2 for subgraph benchmarking.")
                raise ValueError("N must be at least 2 for shortest path benchmarking.")
            if tab_id == "subgraph" and n_ref is not None and int(round(n_ref)) < 3:
                raise ValueError("N must be at least 3 for subgraph benchmarking.")

        primary_var = selected_vars[0]
        secondary_var = selected_vars[1] if len(selected_vars) == 2 else None
        datapoints = []
        if run_mode == "timed":
            timed_probe = dict(fixed_values)
            for var_id in selected_vars:
                timed_probe[var_id] = timed_start[var_id]
            if tab_id == "subgraph":
                n_nodes = int(round(timed_probe["n"]))
                if n_nodes < 3:
                    raise ValueError("N must be at least 3 for subgraph benchmarking.")
                k_value = float(timed_probe["k"])
                if k_mode == "percent":
                    if k_value <= 0 or k_value > 100:
                        raise ValueError("k % of N must be in (0, 100].")
                else:
                    if int(round(k_value)) < 2:
                        raise ValueError("K (nodes) must be >= 2.")
                    if int(round(k_value)) >= n_nodes:
                        raise ValueError("K (nodes) must be smaller than N in subgraph mode.")
            elif tab_id == "shortest_path":
                n_nodes = int(round(timed_probe["n"]))
                if n_nodes < 2:
                    raise ValueError("N must be at least 2 for shortest path benchmarking.")
        else:
            if secondary_var is None:
                for x in var_ranges[primary_var]:
                    point = dict(fixed_values)
                    point.update({primary_var: x})
                    datapoints.append(point)
            else:
                for y in var_ranges[secondary_var]:
                    for x in var_ranges[primary_var]:
                        point = dict(fixed_values)
                        point.update({primary_var: x, secondary_var: y})
                        datapoints.append(point)

            if tab_id == "subgraph":
                for point in datapoints:
                    n_nodes = int(round(point["n"]))
                    if n_nodes < 3:
                        raise ValueError("N must be at least 3 for subgraph benchmarking.")
                    k_value = float(point["k"])
                    if k_mode == "percent":
                        if k_value <= 0 or k_value > 100:
                            raise ValueError("k % of N must be in (0, 100].")
                        # k is defined as a percentage of N; round and clamp to a valid pattern size.
                        k_nodes = int(round((k_value / 100.0) * n_nodes))
                        k_nodes = max(2, min(n_nodes - 1, k_nodes))
                    else:
                        k_nodes = int(round(k_value))
                        if k_nodes < 2:
                            raise ValueError("K (nodes) must be >= 2.")
                        if k_nodes >= n_nodes:
                            raise ValueError("K (nodes) must be smaller than N in subgraph mode.")
                    point["k_nodes"] = k_nodes

        return {
            "tab_id": tab_id,
            "input_mode": "independent",
            "graph_family": generator_mod.normalize_graph_family(self.graph_family_var.get()),
            "selected_datasets": [],
            "selected_variants": [variant.variant_id for variant in selected_variants],
            "selected_variant_labels": {variant.variant_id: variant.label for variant in selected_variants},
            "iterations": iterations,
            "base_seed": base_seed,
            "run_mode": run_mode,
            "time_limit_minutes": time_limit_minutes,
            "solver_timeout_seconds": solver_timeout_seconds,
            "failure_policy": failure_policy,
            "retry_failed_trials": retry_failed_trials,
            "timeout_as_missing": timeout_as_missing,
            "outlier_filter": outlier_filter,
            "k_mode": k_mode,
            "primary_var": primary_var,
            "secondary_var": secondary_var,
            "var_ranges": var_ranges,
            "fixed_values": fixed_values,
            "datapoints": datapoints,
            "timed_start": timed_start,
            "timed_step": timed_step,
            "input_specs": input_specs,
            "plot3d_style": style,
            "plot3d_variant": variant_for_3d,
            "show_stddev_bars": bool(self.show_stddev_var.get()),
            "show_regression_line": bool(self.show_regression_var.get()),
            "show_trendlines_only": bool(self.show_trendlines_only_var.get()),
            "parallel_requested": parallel_requested,
            "requested_workers": requested_workers,
            "max_workers": max_workers,
            "detected_logical_cores": detected_cores,
            "delete_generated_inputs": bool(self.delete_generated_inputs_var.get()),
            "warmup_trials": int(DEFAULT_DISCARDED_WARMUP_TRIALS),
        }

    def _start_run(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning(APP_TITLE, "A benchmark run is already active.")
            return
        try:
            config = self._validate_and_build_config()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self.stop_event.clear()
        self.pause_event.clear()
        self._flush_visualizer_caches(delete_disk=True)
        self.session_output_dir = make_session_output_dir()
        self.last_run_payload = None
        self._reset_visualizer_selection_state()
        self._clear_visualizer_render()
        self._clear_graphs(announce=False)
        self._clear_drilldown()
        self._append_log("Cleared previous graphs for new run.", level="notice")
        deadline = self._start_run_timer(config["time_limit_minutes"] if config["run_mode"] == "timed" else None)
        config["deadline_monotonic"] = deadline
        self._append_log(f"Output directory: {self.session_output_dir}")
        datapoints_label = str(len(config["datapoints"])) if config["run_mode"] != "timed" else "unbounded (timed)"
        input_mode = str(config.get("input_mode") or "independent").strip().lower()
        if input_mode == "datasets":
            selected_dataset_ids = list(config.get("selected_datasets") or [])
            variable_segments = (
                f"input_mode=datasets | selected_datasets={len(selected_dataset_ids)}"
            )
        else:
            vars_for_log = ["n", "density"] if config["tab_id"] == "shortest_path" else ["n", "k", "density"]
            variable_segments = " | ".join(self._format_run_input_segment(config, var_id) for var_id in vars_for_log)
        if config["parallel_requested"] and config["requested_workers"] > config["max_workers"]:
            self._append_log(
                f"Parallel workers clamped from {config['requested_workers']} to {config['max_workers']} "
                f"(detected logical cores={config['detected_logical_cores']}).",
                level="notice",
            )
        parallel_mode = "on" if config["max_workers"] > 1 else "off"
        timeout_mode = "off" if config.get("solver_timeout_seconds") is None else f"{float(config['solver_timeout_seconds']):.1f}s"
        failure_mode = config.get("failure_policy", "stop")
        retry_count = int(config.get("retry_failed_trials", 0))
        timeout_mode_policy = "missing" if config.get("timeout_as_missing", True) else "strict"
        outlier_mode = str(config.get("outlier_filter", "none")).strip().lower()
        self._append_log(
            f"Starting run | tab={config['tab_id']} | variants={len(config['selected_variants'])} | "
            f"datapoints={datapoints_label} | iterations={config['iterations']} | "
            f"parallel={parallel_mode} workers={config['max_workers']} cores={config['detected_logical_cores']} | "
            f"solver_timeout={timeout_mode} | "
            f"failure_policy={failure_mode} retries={retry_count} timeout_policy={timeout_mode_policy} | "
            f"outlier_filter={outlier_mode} min_samples={DEFAULT_OUTLIER_MIN_SAMPLES} | "
            f"delete_generated_inputs={'on' if config.get('delete_generated_inputs') else 'off'} | "
            f"{variable_segments}"
        )
        if input_mode == "datasets":
            selected_dataset_ids = list(config.get("selected_datasets") or [])
            selected_dataset_names = []
            for dataset_id in selected_dataset_ids:
                spec = self.dataset_spec_by_id.get(str(dataset_id).strip().lower())
                selected_dataset_names.append(spec.name if spec is not None else str(dataset_id))
            if selected_dataset_names:
                self._append_log("Datasets: " + ", ".join(selected_dataset_names), level="notice")

        self.run_btn.configure(state=tk.DISABLED)
        self.abort_btn.configure(state=tk.NORMAL)
        self.pause_btn.configure(state=tk.NORMAL, text="Pause")
        self.open_dir_btn.configure(state=tk.NORMAL)
        self.save_btn.configure(state=tk.DISABLED)
        self.load_visualizer_btn.configure(state=tk.DISABLED)
        self.open_visualizer_btn.configure(state=tk.DISABLED)
        self.visualizer_fullscreen_btn.configure(state=tk.DISABLED)
        if self.visualizer_global_autoplay_btn is not None:
            self.visualizer_global_autoplay_btn.configure(state=tk.DISABLED)
        self.visualizer_status_var.set("Run in progress. Visualizer will be available after completion.")

        self.worker_thread = threading.Thread(target=self._run_worker, args=(config,), daemon=True)
        self.worker_thread.start()

    def _abort_run(self):
        self.stop_event.set()
        self.pause_event.clear()
        self._set_process_pause_state(paused=False)
        with self.active_proc_lock:
            procs = list(self.active_procs)
        for proc in procs:
            if proc.poll() is not None:
                continue
            try:
                proc.terminate()
            except Exception:
                pass
        self._append_log("Abort requested.")

    def _toggle_pause(self):
        if not (self.worker_thread and self.worker_thread.is_alive()):
            return
        if self.pause_event.is_set():
            self._set_process_pause_state(paused=False)
            self.pause_event.clear()
            self.pause_btn.configure(text="Pause")
            self._append_log("Run resumed.", level="notice")
        else:
            self.pause_event.set()
            self._set_process_pause_state(paused=True)
            self._clear_live_log_line()
            self.pause_btn.configure(text="Resume")
            self._append_log("Run paused. Active solver processes suspended; no new trials will start.", level="warn")

    def _set_process_pause_state(self, paused: bool):
        with self.active_proc_lock:
            procs = list(self.active_procs)
        if paused:
            for proc in procs:
                if proc.poll() is not None:
                    continue
                try:
                    psutil.Process(proc.pid).suspend()
                    self.suspended_proc_pids.add(int(proc.pid))
                except Exception:
                    pass
        else:
            pids = set(self.suspended_proc_pids)
            self.suspended_proc_pids.clear()
            for pid in pids:
                try:
                    psutil.Process(pid).resume()
                except Exception:
                    pass

    def _estimate_run(self):
        try:
            config = self._validate_and_build_config()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        variants = len(config["selected_variants"])
        iterations = int(config["iterations"])
        mode = config["run_mode"]
        input_mode = str(config.get("input_mode") or "independent").strip().lower()
        warmups_per_variant = int(config.get("warmup_trials", 0))
        if input_mode == "datasets":
            warmups_per_variant = 0
        warmups = warmups_per_variant * variants
        lines = [
            "Run Estimate",
            f"Tab: {config['tab_id']}",
            f"Input mode: {input_mode}",
            f"Variants: {variants}",
            f"Iterations per datapoint: {iterations}",
            f"Discarded warm-up solver calls: {warmups}",
        ]
        if input_mode == "datasets":
            datapoints = len(config["datapoints"])
            measured_trials = datapoints * variants * iterations
            streamed_rows = datapoints * variants
            selected_dataset_ids = list(config.get("selected_datasets") or [])
            lines.extend(
                [
                    "Mode: threshold (datasets)",
                    f"Selected datasets: {len(selected_dataset_ids)}",
                    f"Datapoints (datasets): {datapoints}",
                    f"Measured solver calls: {measured_trials}",
                    f"Total solver calls (including warm-up): {measured_trials + warmups}",
                    f"Result rows (NDJSON/CSV): {streamed_rows}",
                ]
            )
        elif mode == "threshold":
            datapoints = len(config["datapoints"])
            measured_trials = datapoints * variants * iterations
            streamed_rows = datapoints * variants
            generated_iter_dirs = datapoints * iterations
            lines.extend([
                f"Mode: threshold",
                f"Datapoints: {datapoints}",
                f"Measured solver calls: {measured_trials}",
                f"Total solver calls (including warm-up): {measured_trials + warmups}",
                f"Generated iteration folders: {generated_iter_dirs} (+ warm-up folders)",
                f"Result rows (NDJSON/CSV): {streamed_rows}",
            ])
        else:
            per_datapoint_calls = variants * iterations
            primary_var = config["primary_var"]
            secondary_var = config["secondary_var"]
            primary_cap = self._timed_max_index(config, primary_var)
            secondary_cap = self._timed_max_index(config, secondary_var) if secondary_var is not None else None
            bounded_cap = None
            if secondary_var is None and primary_cap is not None:
                bounded_cap = primary_cap + 1
            elif secondary_var is not None and primary_cap is not None and secondary_cap is not None:
                bounded_cap = (primary_cap + 1) * (secondary_cap + 1)
            lines.extend([
                "Mode: timed",
                f"Per-datapoint solver calls: {per_datapoint_calls}",
                f"Total solver calls: unbounded until timer/abort",
            ])
            if bounded_cap is not None:
                lines.append(f"Unique bounded datapoint cap: {bounded_cap}")
            else:
                lines.append("Unique bounded datapoint cap: unbounded")
        messagebox.showinfo(APP_TITLE, "\n".join(lines))

    def _timed_value_for_index(self, config: dict, var_id: str, index: int) -> float:
        start = float(config["timed_start"][var_id])
        step = float(config["timed_step"][var_id])
        value = start + (step * float(index))
        if var_id == "n":
            return float(int(round(value)))
        if var_id == "density":
            return max(0.000001, min(1.0, float(value)))
        if var_id == "k":
            if self._k_mode(config) == "absolute":
                return float(max(2, int(round(value))))
            return max(0.000001, min(100.0, float(value)))
        return float(value)

    def _timed_upper_bound(self, var_id: str, config: dict | None = None) -> float | None:
        if var_id == "density":
            return 1.0
        if var_id == "k":
            if self._k_mode(config) == "absolute":
                return None
            return 100.0
        return None

    def _timed_max_index(self, config: dict, var_id: str) -> int | None:
        upper = self._timed_upper_bound(var_id, config)
        if upper is None:
            return None
        start = float(config["timed_start"][var_id])
        step = float(config["timed_step"][var_id])
        if step <= 0:
            return 0
        if start >= upper:
            return 0
        return max(0, int(math.ceil(((upper - start) / step) - 1e-12)))

    def _build_timed_datapoint(self, config: dict, index_by_var: dict[str, int]):
        point = dict(config["fixed_values"])
        for var_id, idx in index_by_var.items():
            point[var_id] = self._timed_value_for_index(config, var_id, idx)
        if config["tab_id"] == "subgraph":
            n_nodes = int(round(float(point["n"])))
            if n_nodes < 3:
                raise ValueError("N must be at least 3 for subgraph benchmarking.")
            density_value = max(0.000001, min(1.0, float(point["density"])))
            k_mode = self._k_mode(config)
            k_raw = float(point["k"])
            point["n"] = float(n_nodes)
            point["density"] = density_value
            if k_mode == "absolute":
                k_nodes = int(round(k_raw))
                if k_nodes < 2:
                    raise ValueError("K (nodes) must be >= 2.")
                if k_nodes >= n_nodes:
                    raise ValueError("K (nodes) must be smaller than N in subgraph mode.")
                point["k"] = float(k_nodes)
            else:
                k_percent = max(0.000001, min(100.0, k_raw))
                point["k"] = k_percent
                k_nodes = int(round((k_percent / 100.0) * n_nodes))
                k_nodes = max(2, min(n_nodes - 1, k_nodes))
            point["k_nodes"] = k_nodes
        return point

    def _iter_timed_datapoints(self, config: dict):
        primary_var = config["primary_var"]
        secondary_var = config["secondary_var"]
        primary_cap = self._timed_max_index(config, primary_var)
        secondary_cap = self._timed_max_index(config, secondary_var) if secondary_var is not None else None

        if secondary_var is None:
            if primary_cap is None:
                point_idx = 0
                while True:
                    yield point_idx, self._build_timed_datapoint(config, {primary_var: point_idx})
                    point_idx += 1
            else:
                for point_idx in range(primary_cap + 1):
                    yield point_idx, self._build_timed_datapoint(config, {primary_var: point_idx})
            return

        point_idx = 0
        if primary_cap is None and secondary_cap is None:
            level = 0
            while True:
                for primary_idx in range(level + 1):
                    idx_map = {primary_var: primary_idx, secondary_var: level}
                    yield point_idx, self._build_timed_datapoint(config, idx_map)
                    point_idx += 1
                for secondary_idx in range(level):
                    idx_map = {primary_var: level, secondary_var: secondary_idx}
                    yield point_idx, self._build_timed_datapoint(config, idx_map)
                    point_idx += 1
                level += 1
            return

        if primary_cap is None and secondary_cap is not None:
            primary_idx = 0
            while True:
                for secondary_idx in range(secondary_cap + 1):
                    idx_map = {primary_var: primary_idx, secondary_var: secondary_idx}
                    yield point_idx, self._build_timed_datapoint(config, idx_map)
                    point_idx += 1
                primary_idx += 1
            return

        if primary_cap is not None and secondary_cap is None:
            secondary_idx = 0
            while True:
                for primary_idx in range(primary_cap + 1):
                    idx_map = {primary_var: primary_idx, secondary_var: secondary_idx}
                    yield point_idx, self._build_timed_datapoint(config, idx_map)
                    point_idx += 1
                secondary_idx += 1
            return

        for secondary_idx in range(int(secondary_cap) + 1):
            for primary_idx in range(int(primary_cap) + 1):
                idx_map = {primary_var: primary_idx, secondary_var: secondary_idx}
                yield point_idx, self._build_timed_datapoint(config, idx_map)
                point_idx += 1

    def _iter_config_datapoints(self, config: dict):
        if config["run_mode"] == "timed":
            yield from self._iter_timed_datapoints(config)
        else:
            for idx, point in enumerate(config["datapoints"]):
                yield idx, point

    def _run_worker(self, config: dict):
        started_at = dt.datetime.now(dt.timezone.utc)
        deadline = config.get("deadline_monotonic")
        if deadline is None and config["run_mode"] == "timed" and config["time_limit_minutes"] is not None:
            deadline = time.monotonic() + float(config["time_limit_minutes"]) * 60.0
        timed_out = False
        aborted = False
        total_trials_planned = None if config["run_mode"] == "timed" else len(config["datapoints"]) * len(config["selected_variants"]) * config["iterations"]
        completed_trials = 0
        streamed_datapoint_rows = 0

        generated_root = self.session_output_dir / "generated_inputs"
        generated_root.mkdir(parents=True, exist_ok=True)
        datapoints_stream_path = self.session_output_dir / "benchmark-datapoints.ndjson"
        datapoints_stream_fh = None
        try:
            if datapoints_stream_path.exists():
                datapoints_stream_path.unlink()
        except Exception:
            pass
        observed_var_values = {config["primary_var"]: set()}
        if config["secondary_var"] is not None:
            observed_var_values[config["secondary_var"]] = set()
        timeout_notice_emitted = False
        timeout_completion_notice_emitted = False
        timed_points_exhausted = False
        selected_variants = list(config["selected_variants"])
        if config["tab_id"] == "subgraph":
            accuracy_baseline_variant = "vf3_baseline"
        else:
            families_in_selection = {variant_family_from_id(v) for v in selected_variants}
            if "dijkstra" in families_in_selection:
                accuracy_baseline_variant = "dijkstra_baseline"
            elif "sp_via" in families_in_selection:
                accuracy_baseline_variant = "sp_via_baseline"
            else:
                accuracy_baseline_variant = "dijkstra_baseline"
        solver_timeout_seconds = config.get("solver_timeout_seconds")
        input_mode = str(config.get("input_mode") or "independent").strip().lower()
        warmup_trials = int(max(0, config.get("warmup_trials", 0)))
        if input_mode == "datasets":
            warmup_trials = 0
        failure_policy = str(config.get("failure_policy", "stop")).strip().lower()
        retry_failed_trials = int(max(0, config.get("retry_failed_trials", 0)))
        timeout_as_missing = bool(config.get("timeout_as_missing", True))
        parallel_workers = int(max(1, config.get("max_workers", 1)))
        executor: concurrent.futures.ThreadPoolExecutor | None = concurrent.futures.ThreadPoolExecutor(
            max_workers=parallel_workers,
            thread_name_prefix="solver",
        )

        if config["run_mode"] == "timed":
            bounded_vars = []
            for v in (config["primary_var"], config["secondary_var"]):
                if v == "density":
                    bounded_vars.append(v)
                elif v == "k" and self._k_mode(config) == "percent":
                    bounded_vars.append(v)
            if bounded_vars:
                bounded_labels = ", ".join(self._axis_label(v, config) for v in bounded_vars)
                bounded_verb = "is" if len(bounded_vars) == 1 else "are"
                self._append_log_threadsafe(
                    f"Timed mode note: {bounded_labels} {bounded_verb} bounded; duplicate capped datapoints are skipped automatically.",
                    level="notice",
                )

        try:
            datapoints_stream_fh = datapoints_stream_path.open("w", encoding="utf-8", newline="\n")
            if warmup_trials > 0:
                try:
                    _warmup_point_idx, warmup_point = next(self._iter_config_datapoints(config))
                except StopIteration:
                    warmup_point = None
                if warmup_point is not None:
                    warmup_token = "warmup-progress"
                    self._set_live_log_line_threadsafe(warmup_token, "Warming up...", level="notice")
                    warmup_root = generated_root / "_warmup"
                    warmup_root.mkdir(parents=True, exist_ok=True)
                    for warmup_iter in range(warmup_trials):
                        while self.pause_event.is_set():
                            if self.stop_event.is_set():
                                raise RunAbortedError("Abort requested")
                            time.sleep(0.1)
                        if self.stop_event.is_set():
                            raise RunAbortedError("Abort requested")
                        warmup_seed = int((int(config["base_seed"]) + 700_000_000 + warmup_iter) % 2_147_483_647)
                        if warmup_seed <= 0:
                            warmup_seed = warmup_iter + 1
                        warmup_dir = warmup_root / f"trial_{warmup_iter + 1:03d}"
                        warmup_dir.mkdir(parents=True, exist_ok=True)
                        n_value = int(round(warmup_point["n"]))
                        density_value = float(warmup_point["density"])
                        k_value = int(round(warmup_point.get("k_nodes", 1)))
                        if str(config.get("input_mode") or "independent").strip().lower() == "datasets":
                            generated_warmup = self._resolve_dataset_inputs_for_run(warmup_point)
                        elif config["tab_id"] == "shortest_path":
                            generated_warmup = {
                                "dijkstra_file": generate_dijkstra_inputs(
                                    warmup_dir,
                                    n_value,
                                    density_value,
                                    warmup_seed,
                                    graph_family=str(config.get("graph_family") or "random_density"),
                                )
                            }
                        else:
                            generated_warmup = generate_subgraph_inputs(
                                warmup_dir,
                                n_value,
                                k_value,
                                density_value,
                                warmup_seed,
                                graph_family=str(config.get("graph_family") or "random_density"),
                            )
                        for variant_id in selected_variants:
                            while self.pause_event.is_set():
                                if self.stop_event.is_set():
                                    raise RunAbortedError("Abort requested")
                                time.sleep(0.1)
                            if self.stop_event.is_set():
                                raise RunAbortedError("Abort requested")
                            warmup_label = (
                                f"warm-up {warmup_iter + 1}/{warmup_trials}, "
                                f"{config['selected_variant_labels'].get(variant_id, variant_id)}"
                            )
                            self._run_solver_variant(
                                variant_id,
                                generated_warmup,
                                heartbeat_label=warmup_label,
                                solver_timeout_seconds=solver_timeout_seconds,
                            )
                        self._set_live_log_line_threadsafe(
                            warmup_token,
                            f"Warming up{'.' * (3 + warmup_iter + 1)}",
                            level="notice",
                        )
                    if config.get("delete_generated_inputs", True):
                        try:
                            shutil.rmtree(warmup_root, ignore_errors=False)
                        except FileNotFoundError:
                            pass
                        except Exception as warmup_cleanup_exc:
                            self._append_log_threadsafe(
                                f"Update: failed to delete warm-up inputs: {warmup_cleanup_exc}",
                                level="warn",
                            )
                    self._clear_live_log_line_threadsafe(token=warmup_token)
                    self._append_log_threadsafe("Warm-up complete. Beginning measured datapoints.", level="notice")

            point_states: dict[int, dict] = {}
            datapoint_iter = self._iter_config_datapoints(config)
            future_map: dict[concurrent.futures.Future, dict] = {}
            submission_closed = False
            fatal_error: Exception | None = None
            cursor = {
                "point_idx": None,
                "point": None,
                "state": None,
                "iter_idx": 0,
                "variant_pos": 0,
                "generated": None,
                "iter_seed": None,
            }

            def _record_trial_completion():
                nonlocal completed_trials
                completed_trials += 1
                if total_trials_planned is None:
                    if completed_trials % 5 == 0:
                        self._append_log_threadsafe(f"Progress: {completed_trials} trial runs complete (timed mode)")
                else:
                    if completed_trials % 5 == 0 or completed_trials == total_trials_planned:
                        self._append_log_threadsafe(f"Progress: {completed_trials}/{total_trials_planned} trial runs complete")

            def _finalize_datapoint_if_ready(state: dict):
                nonlocal timeout_completion_notice_emitted, streamed_datapoint_rows
                if state.get("logged"):
                    return
                if not state.get("submission_done"):
                    return
                if int(state.get("completed_trials", 0)) < int(state.get("submitted_trials", 0)):
                    return

                x_value = float(state["x_value"])
                y_value = float(state["y_value"]) if state["y_value"] is not None else None
                outlier_mode = str(config.get("outlier_filter", "none")).strip().lower()
                for variant_id in selected_variants:
                    runtimes_raw = [float(v) for v in state["samples_runtime"][variant_id]]
                    memories_raw = [float(v) for v in state["samples_memory"][variant_id]]
                    runtimes = filter_outlier_samples(runtimes_raw, outlier_mode)
                    memories = filter_outlier_samples(memories_raw, outlier_mode)
                    answer_rows = list(state["answer_rows"][variant_id])
                    if not runtimes_raw and not memories_raw:
                        if timed_out or aborted:
                            continue
                    row = {
                        "variant_id": variant_id,
                        "variant_label": config["selected_variant_labels"].get(variant_id, variant_id),
                        "x_value": x_value,
                        "y_value": y_value,
                        "point_label": str(state.get("point_label") or ""),
                        "dataset_id": state.get("dataset_id"),
                        "dataset_name": state.get("dataset_name"),
                        "outlier_filter_mode": outlier_mode,
                        "outlier_filter_min_samples": int(DEFAULT_OUTLIER_MIN_SAMPLES),
                        "runtime_median_ms": median_or_none(runtimes),
                        "runtime_stdev_ms": safe_stdev(runtimes),
                        "runtime_samples_n": len(runtimes),
                        "runtime_samples_total_n": len(runtimes_raw),
                        "memory_median_kb": median_or_none(memories),
                        "memory_stdev_kb": safe_stdev(memories),
                        "memory_samples_n": len(memories),
                        "memory_samples_total_n": len(memories_raw),
                        "completed_iterations": int(state["completed_iterations"]),
                        "requested_iterations": config["iterations"],
                        "seeds": list(state["seed_records"][variant_id]),
                        "runtime_samples_ms": [float(v) for v in runtimes],
                        "runtime_samples_raw_ms": [float(v) for v in runtimes_raw],
                        "memory_samples_kb": [float(v) for v in memories],
                        "memory_samples_raw_kb": [float(v) for v in memories_raw],
                        "answer_kind": next((item.get("answer_kind") for item in answer_rows if item.get("answer_kind")), None),
                        "path_length_median": median_or_none([float(item.get("path_length")) for item in answer_rows if isinstance(item.get("path_length"), (int, float))]),
                    }
                    datapoints_stream_fh.write(json.dumps(row, default=serialize_for_json) + "\n")
                    streamed_datapoint_rows += 1

                combined_runtime_samples: list[float] = []
                for variant_id in selected_variants:
                    combined_runtime_samples.extend(
                        filter_outlier_samples(
                            [float(v) for v in state["samples_runtime"][variant_id]],
                            outlier_mode,
                        )
                    )
                combined_median_runtime = median_or_none(combined_runtime_samples)
                median_runtime_text = (
                    "combined median runtime=n/a"
                    if combined_median_runtime is None
                    else f"combined median runtime={combined_median_runtime:.3f} ms"
                )
                point_idx = int(state["point_idx"]) + 1
                point_label = str(state["point_label"])
                if config["run_mode"] == "timed":
                    self._append_log_threadsafe(f"Datapoint {point_idx} complete ({point_label}) | {median_runtime_text}")
                else:
                    self._append_log_threadsafe(f"Datapoint {point_idx}/{len(config['datapoints'])} complete ({point_label}) | {median_runtime_text}")
                state["logged"] = True
                try:
                    datapoints_stream_fh.flush()
                except Exception:
                    pass

                if config.get("delete_generated_inputs", True) and not state.get("inputs_deleted", False):
                    point_dir = state.get("point_dir")
                    if point_dir is not None:
                        try:
                            shutil.rmtree(point_dir, ignore_errors=False)
                        except FileNotFoundError:
                            pass
                        except Exception as cleanup_exc:
                            self._append_log_threadsafe(
                                f"Update: failed to delete generated inputs for datapoint {point_idx}: {cleanup_exc}",
                                level="warn",
                            )
                    state["inputs_deleted"] = True

                if timed_out and timeout_notice_emitted and not timeout_completion_notice_emitted:
                    self._append_log_threadsafe(
                        "Timed limit reached earlier; queued trials/datapoints have now completed.",
                        level="success",
                    )
                    timeout_completion_notice_emitted = True

            def _build_context_error(trial: dict, inner_exc: Exception):
                point = trial["point"]
                context_bits = [
                    f"seed={trial['iter_seed']}",
                    f"N={int(round(point.get('n', 0)))}",
                    f"Density={float(point.get('density', 0.0)):.6f}",
                ]
                if config["tab_id"] == "subgraph":
                    if self._k_mode(config) == "absolute":
                        context_bits.append(f"k_nodes_input={int(round(point.get('k', 0.0)))}")
                    else:
                        context_bits.append(f"k%={float(point.get('k', 0.0)):.4f}")
                    context_bits.append(f"k_nodes={int(round(point.get('k_nodes', 0)))}")
                return RuntimeError(f"{inner_exc} | context: {', '.join(context_bits)}")

            def _mark_cursor_submission_done():
                state = cursor.get("state")
                if isinstance(state, dict):
                    state["submission_done"] = True

            def _next_trial():
                while True:
                    if cursor["point"] is None:
                        point_idx, point = next(datapoint_iter)
                        x_value = float(point[config["primary_var"]])
                        y_value = float(point[config["secondary_var"]]) if config["secondary_var"] else None
                        observed_var_values[config["primary_var"]].add(x_value)
                        if config["secondary_var"] is not None and y_value is not None:
                            observed_var_values[config["secondary_var"]].add(y_value)
                        if str(config.get("input_mode") or "independent").strip().lower() == "datasets":
                            dataset_name = str(point.get("dataset_name") or point.get("dataset_id") or f"dataset_{point_idx + 1}")
                            point_label = f"dataset={dataset_name}"
                        else:
                            point_label = f"{config['primary_var']}={self._format_point_value(config['primary_var'], x_value, config)}"
                            if config["secondary_var"] is not None and y_value is not None:
                                point_label += f", {config['secondary_var']}={self._format_point_value(config['secondary_var'], y_value, config)}"
                        state = {
                            "point_idx": point_idx,
                            "point_label": point_label,
                            "dataset_id": (str(point.get("dataset_id") or "").strip() if str(config.get("input_mode") or "independent").strip().lower() == "datasets" else None),
                            "dataset_name": (str(point.get("dataset_name") or "").strip() if str(config.get("input_mode") or "independent").strip().lower() == "datasets" else None),
                            "x_value": x_value,
                            "y_value": y_value,
                            "point_dir": (
                                None
                                if str(config.get("input_mode") or "independent").strip().lower() == "datasets"
                                else generated_root / f"point_{point_idx + 1:05d}"
                            ),
                            "samples_runtime": {variant_id: [] for variant_id in selected_variants},
                            "samples_memory": {variant_id: [] for variant_id in selected_variants},
                            "seed_records": {variant_id: [] for variant_id in selected_variants},
                            "submitted_trials": 0,
                            "completed_trials": 0,
                            "submission_done": False,
                            "completed_iterations": 0,
                            "iter_pending": {iter_idx: set(selected_variants) for iter_idx in range(config["iterations"])},
                            "iter_solution_counts": {iter_idx: {} for iter_idx in range(config["iterations"])},
                            "iter_answer_signatures": {iter_idx: {} for iter_idx in range(config["iterations"])},
                            "iter_runtime_ms": {iter_idx: {} for iter_idx in range(config["iterations"])},
                            "iter_success_count": {iter_idx: 0 for iter_idx in range(config["iterations"])},
                            "answer_rows": {variant_id: [] for variant_id in selected_variants},
                            "inputs_deleted": False,
                            "logged": False,
                        }
                        point_states[point_idx] = state
                        cursor["point_idx"] = point_idx
                        cursor["point"] = point
                        cursor["state"] = state
                        cursor["iter_idx"] = 0
                        cursor["variant_pos"] = 0
                        cursor["generated"] = None
                        cursor["iter_seed"] = None

                    if int(cursor["iter_idx"]) >= int(config["iterations"]):
                        state = cursor["state"]
                        if isinstance(state, dict):
                            state["submission_done"] = True
                        cursor["point_idx"] = None
                        cursor["point"] = None
                        cursor["state"] = None
                        cursor["iter_idx"] = 0
                        cursor["variant_pos"] = 0
                        cursor["generated"] = None
                        cursor["iter_seed"] = None
                        continue

                    point = cursor["point"]
                    if cursor["generated"] is None:
                        point_idx = int(cursor["point_idx"])
                        iter_idx = int(cursor["iter_idx"])
                        iter_seed = int(config["base_seed"]) + (point_idx * 100000) + iter_idx
                        if str(config.get("input_mode") or "independent").strip().lower() == "datasets":
                            generated = self._resolve_dataset_inputs_for_run(point)
                        else:
                            point_dir = cursor["state"]["point_dir"]
                            iter_dir = point_dir / f"iter_{iter_idx + 1:03d}"
                            iter_dir.mkdir(parents=True, exist_ok=True)
                            n_value = int(round(point["n"]))
                            density_value = float(point["density"])
                            k_value = int(round(point.get("k_nodes", 1)))
                            if config["tab_id"] == "shortest_path":
                                generated = {
                                    "dijkstra_file": generate_dijkstra_inputs(
                                        iter_dir,
                                        n_value,
                                        density_value,
                                        iter_seed,
                                        graph_family=str(config.get("graph_family") or "random_density"),
                                    )
                                }
                            else:
                                generated = generate_subgraph_inputs(
                                    iter_dir,
                                    n_value,
                                    k_value,
                                    density_value,
                                    iter_seed,
                                    graph_family=str(config.get("graph_family") or "random_density"),
                                )
                        cursor["generated"] = generated
                        cursor["iter_seed"] = iter_seed

                    variant_pos = int(cursor["variant_pos"])
                    variant_id = selected_variants[variant_pos]
                    iter_idx = int(cursor["iter_idx"])
                    heartbeat_label = (
                        f"datapoint {int(cursor['point_idx']) + 1}, iter {iter_idx + 1}/{config['iterations']}, "
                        f"{config['selected_variant_labels'].get(variant_id, variant_id)}"
                    )
                    trial = {
                        "point_idx": int(cursor["point_idx"]),
                        "point": point,
                        "state": cursor["state"],
                        "iter_idx": iter_idx,
                        "iter_seed": int(cursor["iter_seed"]),
                        "variant_id": variant_id,
                        "generated": cursor["generated"],
                        "heartbeat_label": heartbeat_label,
                        "attempt": 0,
                    }
                    cursor["state"]["submitted_trials"] += 1

                    variant_pos += 1
                    if variant_pos >= len(selected_variants):
                        variant_pos = 0
                        cursor["iter_idx"] = iter_idx + 1
                        cursor["generated"] = None
                        cursor["iter_seed"] = None
                    cursor["variant_pos"] = variant_pos
                    return trial

            while True:
                while not submission_closed and len(future_map) < parallel_workers:
                    if self.pause_event.is_set():
                        break
                    if self.stop_event.is_set():
                        aborted = True
                        submission_closed = True
                        _mark_cursor_submission_done()
                        break

                    if deadline is not None and time.monotonic() >= deadline:
                        timed_out = True
                        submission_closed = True
                        _mark_cursor_submission_done()
                        if not timeout_notice_emitted:
                            self._append_log_threadsafe(
                                "Timed limit reached. Finishing in-flight trials before stopping.",
                                level="warn",
                            )
                            timeout_notice_emitted = True
                        break

                    try:
                        trial = _next_trial()
                    except StopIteration:
                        submission_closed = True
                        if config["run_mode"] == "timed" and not timed_out and not aborted:
                            timed_points_exhausted = True
                            self._append_log_threadsafe(
                                "Timed mode reached all unique datapoints allowed by bounded variables; stopping before duplicate capped datapoints.",
                                level="notice",
                            )
                        break
                    except Exception as exc:
                        fatal_error = exc
                        submission_closed = True
                        self.stop_event.set()
                        break

                    future = executor.submit(
                        self._run_solver_variant,
                        trial["variant_id"],
                        trial["generated"],
                        trial["heartbeat_label"],
                        solver_timeout_seconds,
                    )
                    future_map[future] = trial

                if fatal_error is not None:
                    break
                if not future_map:
                    if submission_closed:
                        break
                    if self.pause_event.is_set():
                        time.sleep(0.1)
                        continue
                    time.sleep(0.05)
                    continue

                done, _pending = concurrent.futures.wait(
                    set(future_map.keys()),
                    timeout=0.2,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                if not done:
                    continue

                for future in done:
                    trial = future_map.pop(future)
                    state = trial["state"]
                    variant_id = trial["variant_id"]
                    iter_idx = int(trial["iter_idx"])
                    attempt = int(trial.get("attempt", 0))
                    success = False
                    solution_count = None
                    answer_signature = None
                    answer_details = None
                    runtime_ms = 0.0
                    peak_kb = 0.0
                    handled_failure = False

                    try:
                        runtime_ms, peak_kb, solution_count, answer_signature, answer_details = future.result()
                        success = True
                    except SolverTimeoutError as exc:
                        if attempt < retry_failed_trials and not self.stop_event.is_set() and not timed_out and not aborted:
                            retry_trial = dict(trial)
                            retry_trial["attempt"] = attempt + 1
                            retry_trial["heartbeat_label"] = (
                                f"{trial['heartbeat_label']} (retry {attempt + 1}/{retry_failed_trials})"
                            )
                            retry_future = executor.submit(
                                self._run_solver_variant,
                                retry_trial["variant_id"],
                                retry_trial["generated"],
                                retry_trial["heartbeat_label"],
                                solver_timeout_seconds,
                            )
                            future_map[retry_future] = retry_trial
                            self._append_log_threadsafe(
                                f"Retry {attempt + 1}/{retry_failed_trials} after timeout for "
                                f"{config['selected_variant_labels'].get(variant_id, variant_id)}.",
                                level="warn",
                            )
                            continue
                        if timeout_as_missing:
                            self._append_log_threadsafe(
                                f"Solver timeout: {config['selected_variant_labels'].get(variant_id, variant_id)} "
                                f"exceeded {exc.timeout_seconds:.1f}s (elapsed {exc.elapsed_seconds:.1f}s); "
                                "recording as missing and continuing.",
                                level="warn",
                            )
                            handled_failure = True
                        elif failure_policy == "continue":
                            self._append_log_threadsafe(
                                f"Timeout treated as failure for {config['selected_variant_labels'].get(variant_id, variant_id)}; continuing.",
                                level="error",
                            )
                            handled_failure = True
                        else:
                            fatal_error = _build_context_error(trial, exc)
                            self.stop_event.set()
                    except RunAbortedError:
                        aborted = True
                    except Exception as exc:
                        if attempt < retry_failed_trials and not self.stop_event.is_set() and not timed_out and not aborted:
                            retry_trial = dict(trial)
                            retry_trial["attempt"] = attempt + 1
                            retry_trial["heartbeat_label"] = (
                                f"{trial['heartbeat_label']} (retry {attempt + 1}/{retry_failed_trials})"
                            )
                            retry_future = executor.submit(
                                self._run_solver_variant,
                                retry_trial["variant_id"],
                                retry_trial["generated"],
                                retry_trial["heartbeat_label"],
                                solver_timeout_seconds,
                            )
                            future_map[retry_future] = retry_trial
                            self._append_log_threadsafe(
                                f"Retry {attempt + 1}/{retry_failed_trials} after failure for "
                                f"{config['selected_variant_labels'].get(variant_id, variant_id)}.",
                                level="warn",
                            )
                            continue
                        if failure_policy == "continue":
                            self._append_log_threadsafe(
                                f"Trial failure for {config['selected_variant_labels'].get(variant_id, variant_id)}; "
                                f"continuing due to failure policy. Details: {_build_context_error(trial, exc)}",
                                level="error",
                            )
                            handled_failure = True
                        else:
                            fatal_error = _build_context_error(trial, exc)
                            self.stop_event.set()

                    pending_set = state["iter_pending"].get(iter_idx)
                    if isinstance(pending_set, set):
                        pending_set.discard(variant_id)

                    if success:
                        state["samples_runtime"][variant_id].append(runtime_ms)
                        state["samples_memory"][variant_id].append(peak_kb)
                        state["seed_records"][variant_id].append(int(trial["iter_seed"]))
                        state["iter_success_count"][iter_idx] = int(state["iter_success_count"][iter_idx]) + 1
                        state["iter_runtime_ms"][iter_idx][variant_id] = float(runtime_ms)
                        if solution_count is not None:
                            state["iter_solution_counts"][iter_idx][variant_id] = solution_count
                        if answer_signature is not None:
                            state["iter_answer_signatures"][iter_idx][variant_id] = answer_signature
                        if isinstance(answer_details, dict):
                            state["answer_rows"][variant_id].append(
                                {
                                    "answer_kind": answer_details.get("answer_kind"),
                                    "path_length": answer_details.get("path_length"),
                                }
                            )
                    elif not handled_failure and fatal_error is None and not aborted:
                        # Defensive fallback: treat unexpected non-success as missing so the datapoint can complete.
                        handled_failure = True

                    state["completed_trials"] = int(state["completed_trials"]) + 1
                    _record_trial_completion()

                    if isinstance(pending_set, set) and len(pending_set) == 0:
                        if config["tab_id"] == "subgraph":
                            known_counts = state["iter_solution_counts"].get(iter_idx, {})
                            if len(known_counts) >= 2 and len(set(known_counts.values())) > 1:
                                labels = config["selected_variant_labels"]
                                details = ", ".join(
                                    f"{labels.get(vid, vid)}={known_counts[vid]}" for vid in sorted(known_counts.keys())
                                )
                                self._append_log_threadsafe(
                                    f"Consistency check mismatch at datapoint {int(state['point_idx']) + 1}, "
                                    f"seed={int(trial['iter_seed'])}: {details}",
                                    level="error",
                                )
                        if int(state["iter_success_count"].get(iter_idx, 0)) == len(selected_variants):
                            state["completed_iterations"] = int(state["completed_iterations"]) + 1

                    _finalize_datapoint_if_ready(state)

                    if fatal_error is not None:
                        break

                if fatal_error is not None:
                    break

            if fatal_error is not None:
                raise fatal_error

            for state in point_states.values():
                if not state.get("submission_done"):
                    state["submission_done"] = True
                _finalize_datapoint_if_ready(state)

            if config["run_mode"] == "timed":
                primary_var = config["primary_var"]
                config["var_ranges"][primary_var] = sorted(observed_var_values.get(primary_var, set()))
                secondary_var = config["secondary_var"]
                if secondary_var is not None:
                    config["var_ranges"][secondary_var] = sorted(observed_var_values.get(secondary_var, set()))
            if datapoints_stream_fh is not None:
                try:
                    datapoints_stream_fh.flush()
                except Exception:
                    pass
                datapoints_stream_fh.close()
                datapoints_stream_fh = None

            ended_at = dt.datetime.now(dt.timezone.utc)
            statistical_tests = build_desktop_runtime_statistical_tests(
                config=config,
                point_states=point_states,
                selected_variants=selected_variants,
                alpha=0.05,
            )
            payload = self._build_payload(
                config,
                started_at,
                ended_at,
                aborted,
                timed_out,
                completed_trials,
                total_trials_planned,
                datapoints_stream_path,
                streamed_datapoint_rows,
                statistical_tests=statistical_tests,
            )
            self.last_run_payload = payload
            self.last_plot_context = payload
            self.after(0, lambda: self._render_plots(payload))
            self._save_exports(payload, self.session_output_dir)

            baseline_label = config["selected_variant_labels"].get(accuracy_baseline_variant, accuracy_baseline_variant)
            if accuracy_baseline_variant not in selected_variants:
                self._append_log_threadsafe(
                    f"Accuracy summary skipped: {baseline_label} is not selected.",
                    level="notice",
                )
            else:
                correct_counts = {variant_id: 0 for variant_id in selected_variants}
                total_counts = {variant_id: 0 for variant_id in selected_variants}
                baseline_trials = 0
                for state in point_states.values():
                    iter_answers = state.get("iter_answer_signatures", {})
                    for iter_idx in range(config["iterations"]):
                        answers = iter_answers.get(iter_idx, {})
                        baseline_answer = answers.get(accuracy_baseline_variant)
                        if baseline_answer is None:
                            continue
                        baseline_trials += 1
                        for variant_id in selected_variants:
                            total_counts[variant_id] += 1
                            if answers.get(variant_id) == baseline_answer:
                                correct_counts[variant_id] += 1
                self._append_log_threadsafe(f"Accuracy vs {baseline_label}:", level="notice")
                if baseline_trials == 0:
                    self._append_log_threadsafe(
                        "No baseline-comparable trials were recorded.",
                        level="warn",
                    )
                for variant_id in selected_variants:
                    correct = int(correct_counts.get(variant_id, 0))
                    total = int(total_counts.get(variant_id, 0))
                    percent = (100.0 * float(correct) / float(total)) if total > 0 else 0.0
                    solver_label = config["selected_variant_labels"].get(variant_id, variant_id)
                    self._append_log_threadsafe(
                        f"[{solver_label}]: {correct}/{total} ({percent:.3f}%)",
                        level="notice",
                    )

            self._append_log_threadsafe("Runtime statistical tests vs family baseline:", level="notice")
            self._append_log_threadsafe(
                "Blurb: t-test checks mean runtime shift, Mann-Whitney checks distribution shift, "
                "and effect sizes quantify practical magnitude.",
                level="notice",
            )
            stats_rows = list(statistical_tests.get("pairs", []))
            if not stats_rows:
                self._append_log_threadsafe("No statistical comparisons available for selected variants.", level="warn")
            for row in stats_rows:
                if not isinstance(row, dict):
                    continue
                n = int(row.get("n", 0) or 0)
                solver_label = str(row.get("variant_label") or row.get("variant_id") or "variant")
                baseline_label = str(row.get("baseline_label") or row.get("baseline_variant_id") or "baseline")
                if n <= 0:
                    self._append_log_threadsafe(
                        f"[{solver_label}] vs [{baseline_label}]: insufficient matched pairs (n=0).",
                        level="warn",
                    )
                    continue
                mean_delta = row.get("mean_delta_ms")
                direction = str(row.get("direction") or "n/a")
                paired = row.get("paired_t_test") if isinstance(row.get("paired_t_test"), dict) else {}
                p_value = paired.get("p_value_two_sided")
                p_text = "n/a" if p_value is None else f"{float(p_value):.6g}"
                effect_sizes = row.get("effect_sizes") if isinstance(row.get("effect_sizes"), dict) else {}
                hedges_g = effect_sizes.get("hedges_g")
                g_text = "n/a" if hedges_g is None else f"{float(hedges_g):.4f}"
                self._append_log_threadsafe(
                    f"[{solver_label}] vs [{baseline_label}]: n={n}, mean_delta={float(mean_delta):.3f} ms, "
                    f"direction={direction}, p={p_text}, hedges_g={g_text}",
                    level="notice",
                )

            status_msg = "Run complete."
            status_level = "success"
            if timed_points_exhausted:
                status_msg = "Run complete: all unique bounded timed datapoints were finished."
                status_level = "success"
            if timed_out:
                status_msg = "Run stopped due to timed limit (in-flight queued trials were completed)."
                status_level = "warn"
            if aborted:
                status_msg = "Run aborted by user."
                status_level = "warn"
            self._append_log_threadsafe(f"Seed used for run: {int(config.get('base_seed', 0))}", level="notice")
            self._append_log_threadsafe(status_msg, level=status_level)
            self._append_log_threadsafe(f"Exports written to: {self.session_output_dir}", level="notice")
        except RunAbortedError:
            self._append_log_threadsafe("Run aborted while executing a solver process.")
        except Exception as exc:
            self._append_log_threadsafe(f"Run failed: {exc}", level="error")
            self.after(0, lambda: messagebox.showerror(APP_TITLE, f"Benchmark run failed:\n{exc}"))
        finally:
            try:
                if datapoints_stream_fh is not None:
                    datapoints_stream_fh.close()
            except Exception:
                pass
            if executor is not None:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
            self._set_process_pause_state(paused=False)
            with self.active_proc_lock:
                self.active_procs.clear()
            self.after(0, self._on_run_finished_ui)

    def _on_run_finished_ui(self):
        self._stop_run_timer(hide=True)
        self.pause_event.clear()
        self._set_process_pause_state(paused=False)
        self._clear_live_log_line()
        self.run_btn.configure(state=tk.NORMAL)
        self.abort_btn.configure(state=tk.DISABLED)
        self.pause_btn.configure(state=tk.DISABLED, text="Pause")
        if self.last_run_payload:
            run_cfg = self.last_run_payload.get("run_config") if isinstance(self.last_run_payload, dict) else None
            input_mode = str(run_cfg.get("input_mode") or "independent").strip().lower() if isinstance(run_cfg, dict) else "independent"
            self.save_btn.configure(state=tk.NORMAL)
            self._refresh_visualizer_controls(self.last_run_payload)
            if input_mode == "datasets":
                self.load_visualizer_btn.configure(state=tk.DISABLED)
                self.open_visualizer_btn.configure(state=tk.DISABLED)
                self.visualizer_fullscreen_btn.configure(state=tk.DISABLED)
                self.visualizer_status_var.set("Visualizer is currently available for generated-input runs only.")
            else:
                self.load_visualizer_btn.configure(state=tk.NORMAL if self.visualizer_point_rows else tk.DISABLED)
                self.open_visualizer_btn.configure(state=tk.NORMAL)
                self.visualizer_fullscreen_btn.configure(state=tk.NORMAL if self.visualizer_point_rows else tk.DISABLED)
                self.visualizer_status_var.set("Ready. Choose a datapoint tuple and click Load In Tab.")
        else:
            self.load_visualizer_btn.configure(state=tk.DISABLED)
            self.open_visualizer_btn.configure(state=tk.DISABLED)
            self.visualizer_fullscreen_btn.configure(state=tk.DISABLED)
            self.visualizer_status_var.set("No run payload available yet.")
        self._update_visualizer_autoplay_controls()

    def _run_solver_variant(
        self,
        variant_id: str,
        generated: dict[str, Path | str],
        heartbeat_label: str | None = None,
        solver_timeout_seconds: float | None = None,
    ):
        binary = self.binary_paths[variant_id]
        if not binary.exists():
            raise FileNotFoundError(f"Missing binary for {variant_id}: {binary}")

        family = variant_family_from_id(variant_id)
        if family in {"dijkstra", "sp_via"}:
            command = [str(binary), str(generated["dijkstra_file"])]
        elif family == "vf3":
            if variant_id == "vf3_baseline":
                # Generated subgraph benchmarks are non-induced and undirected.
                command = [str(binary), "-u", "-r", "0", "-e", str(generated["vf_pattern"]), str(generated["vf_target"])]
            else:
                command = [str(binary), str(generated["vf_pattern"]), str(generated["vf_target"])]
        elif family == "glasgow":
            lad_format = str(generated.get("lad_format") or "lad").strip() or "lad"
            if variant_id == "glasgow_baseline":
                command = [str(binary), "--count-solutions", "--format", lad_format, str(generated["lad_pattern"]), str(generated["lad_target"])]
            else:
                command = [str(binary), str(generated["lad_pattern"]), str(generated["lad_target"])]
        else:
            raise ValueError(f"Unsupported variant: {variant_id}")

        runtime_ms, peak_kb, return_code, stdout_text, stderr_text = self._run_process_with_peak_memory(
            command,
            cwd=binary.parent,
            heartbeat_label=heartbeat_label,
            solver_timeout_seconds=solver_timeout_seconds,
        )
        if return_code != 0:
            detail = stderr_text.strip() or stdout_text.strip()
            stderr_clean = (stderr_text or "").strip()
            stdout_clean = (stdout_text or "").strip()
            if stderr_clean:
                stderr_preview = stderr_clean[:4000]
                if len(stderr_clean) > 4000:
                    stderr_preview += "\n...[stderr truncated]..."
                self._append_log_threadsafe(f"{variant_id} stderr:\n{stderr_preview}", level="error")
            elif stdout_clean:
                stdout_preview = stdout_clean[:4000]
                if len(stdout_clean) > 4000:
                    stdout_preview += "\n...[stdout truncated]..."
                self._append_log_threadsafe(f"{variant_id} stdout:\n{stdout_preview}", level="notice")
            code_u32 = int(return_code) & 0xFFFFFFFF
            code_hex = f"0x{code_u32:08X}"
            cmdline = subprocess.list2cmdline(command)
            raise RuntimeError(f"{variant_id} failed with code {return_code} ({code_hex}) | cmd: {cmdline} | {detail[:300]}")
        combined_output = stdout_text + "\n" + stderr_text
        solution_count = None
        answer_signature = None
        answer_kind = None
        answer_value = None
        distance_signature = None
        if family in {"vf3", "glasgow"}:
            solution_count = parse_solution_count(combined_output)
            if solution_count is not None:
                answer_kind = "solution_count"
                answer_value = int(solution_count)
                answer_signature = ("solution_count", int(solution_count))
        elif family in {"dijkstra", "sp_via"}:
            distance_signature = parse_dijkstra_distance(combined_output)
            if distance_signature is not None:
                answer_kind = "distance"
                answer_value = distance_signature
                answer_signature = ("distance", distance_signature)
        path_tokens = extract_path_tokens(combined_output) if family in {"dijkstra", "sp_via"} else []
        answer_details = {
            "answer_kind": answer_kind,
            "answer_value": answer_value,
            "path_length": max(0, len(path_tokens) - 1) if path_tokens else None,
        }
        return runtime_ms, peak_kb, solution_count, answer_signature, answer_details

    def _run_process_with_peak_memory(
        self,
        command: list[str],
        cwd: Path,
        heartbeat_label: str | None = None,
        solver_timeout_seconds: float | None = None,
    ):
        started = time.perf_counter()
        heartbeat_token = f"hb-{threading.get_ident()}-{time.perf_counter_ns()}"
        last_heartbeat_second = -1
        paused_accumulated = 0.0
        paused_since = None
        heartbeat_hidden_for_pause = False
        popen_kwargs = {
            "args": command,
            "cwd": str(cwd),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": runtime_env_for_binary(Path(command[0])),
        }
        if sys.platform.startswith("win"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            popen_kwargs["startupinfo"] = startupinfo
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.Popen(**popen_kwargs)
        with self.active_proc_lock:
            self.active_procs.add(proc)

        peak_bytes = 0
        ps_proc = None
        try:
            ps_proc = psutil.Process(proc.pid)
        except psutil.Error:
            # Child can exit before psutil attaches; continue without peak memory sampling.
            ps_proc = None
        try:
            while True:
                if self.stop_event.is_set():
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        pass
                    raise RunAbortedError("Abort requested")

                now = time.perf_counter()
                if self.pause_event.is_set():
                    if paused_since is None:
                        paused_since = now
                    if heartbeat_label and not heartbeat_hidden_for_pause:
                        self._clear_live_log_line_threadsafe(token=heartbeat_token)
                        heartbeat_hidden_for_pause = True
                    ret = proc.poll()
                    if ret is not None:
                        break
                    time.sleep(0.05)
                    continue
                if paused_since is not None:
                    paused_accumulated += max(0.0, now - paused_since)
                    paused_since = None
                    last_heartbeat_second = -1
                    heartbeat_hidden_for_pause = False

                elapsed_seconds = max(0.0, now - started - paused_accumulated)
                if solver_timeout_seconds is not None and elapsed_seconds >= float(solver_timeout_seconds):
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    raise SolverTimeoutError(float(solver_timeout_seconds), float(elapsed_seconds))

                if heartbeat_label:
                    elapsed_seconds_int = int(elapsed_seconds)
                    if elapsed_seconds_int >= 15 and elapsed_seconds_int != last_heartbeat_second:
                        self._set_live_log_line_threadsafe(
                            heartbeat_token,
                            f"Update: {heartbeat_label} running for {self._format_hms(elapsed_seconds_int)}",
                            level="notice",
                        )
                        last_heartbeat_second = elapsed_seconds_int

                ret = proc.poll()
                if ps_proc is not None:
                    try:
                        mem_info = ps_proc.memory_info()
                        candidate = getattr(mem_info, "peak_wset", None)
                        if candidate is None:
                            candidate = mem_info.rss
                        if isinstance(candidate, (int, float)):
                            peak_bytes = max(peak_bytes, int(candidate))
                    except psutil.Error:
                        ps_proc = None

                if ret is not None:
                    break
                time.sleep(0.02)

            stdout_text, stderr_text = proc.communicate()
            ended = time.perf_counter()
            runtime_ms = max(0.0, (ended - started) * 1000.0)
            peak_kb = max(0.0, peak_bytes / 1024.0)
            return runtime_ms, peak_kb, int(proc.returncode or 0), stdout_text, stderr_text
        finally:
            if heartbeat_label:
                self._clear_live_log_line_threadsafe(token=heartbeat_token)
            with self.active_proc_lock:
                self.active_procs.discard(proc)

    def _build_payload(
        self,
        config,
        started_at,
        ended_at,
        aborted,
        timed_out,
        completed_trials,
        total_trials_planned,
        datapoints_path: Path,
        streamed_datapoint_rows: int,
        statistical_tests: dict | None = None,
    ):
        duration_ms = (ended_at - started_at).total_seconds() * 1000.0
        payload = {
            "schema_version": "desktop-benchmark-v1",
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "run_started_utc": started_at.isoformat(),
            "run_ended_utc": ended_at.isoformat(),
            "run_duration_ms": duration_ms,
            "aborted": aborted,
            "timed_out": timed_out,
            "completed_trials": completed_trials,
            "planned_trials": total_trials_planned,
            "run_config": {
                "tab_id": config["tab_id"],
                "input_mode": config.get("input_mode", "independent"),
                "graph_family": str(config.get("graph_family") or "random_density"),
                "selected_datasets": list(config.get("selected_datasets") or []),
                "selected_variants": config["selected_variants"],
                "selected_variant_labels": config["selected_variant_labels"],
                "iterations_per_datapoint": config["iterations"],
                "seed": config["base_seed"],
                "stop_mode": config["run_mode"],
                "time_limit_minutes": config["time_limit_minutes"],
                "solver_timeout_seconds": config.get("solver_timeout_seconds"),
                "failure_policy": config.get("failure_policy"),
                "retry_failed_trials": config.get("retry_failed_trials"),
                "timeout_as_missing": config.get("timeout_as_missing"),
                "outlier_filter": config.get("outlier_filter", "none"),
                "outlier_filter_min_samples": int(DEFAULT_OUTLIER_MIN_SAMPLES),
                "k_mode": config.get("k_mode", "percent"),
                "max_workers": config.get("max_workers"),
                "detected_logical_cores": config.get("detected_logical_cores"),
                "primary_variable": config["primary_var"],
                "secondary_variable": config["secondary_var"],
                "var_ranges": config["var_ranges"],
                "fixed_values": config["fixed_values"],
                "input_specs": config.get("input_specs", {}),
                "timed_start": config.get("timed_start", {}),
                "timed_step": config.get("timed_step", {}),
                "plot3d_style": config["plot3d_style"],
                "plot3d_variant": config["plot3d_variant"],
                "show_stddev_bars": config.get("show_stddev_bars"),
                "show_regression_line": config.get("show_regression_line"),
                "show_trendlines_only": config.get("show_trendlines_only"),
                "delete_generated_inputs": config.get("delete_generated_inputs"),
                "warmup_trials": config.get("warmup_trials", 0),
            },
            "datapoints": [],
            "datapoints_path": str(datapoints_path),
            "streamed_datapoint_rows": int(streamed_datapoint_rows),
            "provenance": collect_runtime_provenance(repo_root=Path(__file__).resolve().parents[1]),
        }
        if isinstance(statistical_tests, dict):
            payload["statistical_tests"] = statistical_tests
        return payload

    def _render_figure_in_frame(
        self,
        frame: ttk.Frame,
        fig: Figure,
        existing_canvas: FigureCanvasTkAgg | None,
        pick_handler=None,
        motion_handler=None,
        click_handler=None,
        leave_handler=None,
    ):
        if existing_canvas is not None:
            existing_canvas.get_tk_widget().destroy()
            try:
                existing_canvas.figure.clear()
            except Exception:
                pass
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        if pick_handler is not None:
            try:
                canvas.mpl_connect("pick_event", pick_handler)
            except Exception:
                pass
        if motion_handler is not None:
            try:
                canvas.mpl_connect("motion_notify_event", motion_handler)
            except Exception:
                pass
        if click_handler is not None:
            try:
                canvas.mpl_connect("button_press_event", click_handler)
            except Exception:
                pass
        if leave_handler is not None:
            try:
                canvas.mpl_connect("axes_leave_event", leave_handler)
            except Exception:
                pass
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        return canvas

    def _iter_payload_datapoints(self, payload: dict):
        datapoints = payload.get("datapoints")
        if isinstance(datapoints, list) and datapoints:
            for row in datapoints:
                if isinstance(row, dict):
                    yield row
            return
        datapoints_path = payload.get("datapoints_path")
        if not datapoints_path:
            return
        path = Path(datapoints_path)
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    yield row

    def _collect_payload_datapoints(self, payload: dict):
        return list(self._iter_payload_datapoints(payload))

    def _make_dataset_metric_bar_figure(self, payload: dict, metric: str, datapoints: list[dict]):
        fig = Figure(figsize=(7.5, 5.0), dpi=100)
        ax = fig.add_subplot(111)
        config = payload["run_config"]
        selected_variants = list(config.get("selected_variants") or [])
        label_map = dict(config.get("selected_variant_labels") or {})
        show_stddev = bool(self.show_stddev_var.get())
        use_log_y = bool(self.log_y_scale_var.get())
        y_key = "runtime_median_ms" if metric == "runtime" else "memory_median_kb"
        e_key = "runtime_stdev_ms" if metric == "runtime" else "memory_stdev_kb"

        dataset_ids = [str(item).strip().lower() for item in list(config.get("selected_datasets") or []) if str(item).strip()]
        dataset_labels: list[str] = []
        if dataset_ids:
            for dataset_id in dataset_ids:
                spec = self.dataset_spec_by_id.get(dataset_id)
                dataset_labels.append(spec.name if spec is not None else dataset_id)
        else:
            seen_keys: set[str] = set()
            for row in datapoints:
                key = str(row.get("dataset_id") or row.get("dataset_name") or row.get("point_label") or "").strip()
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                dataset_ids.append(key)
                dataset_labels.append(str(row.get("dataset_name") or key))
        if not dataset_ids:
            ax.text(0.1, 0.5, "No dataset datapoints to plot.", transform=ax.transAxes)
            fig.tight_layout()
            setattr(fig, "_legend_hover_state", None)
            setattr(fig, "_drilldown_pick_map", {})
            setattr(fig, "_drilldown_metric", metric)
            return fig

        lookup_by_id: dict[tuple[str, str], dict] = {}
        lookup_by_name: dict[tuple[str, str], dict] = {}
        for row in datapoints:
            variant_id = str(row.get("variant_id") or "").strip().lower()
            if not variant_id:
                continue
            dataset_id = str(row.get("dataset_id") or "").strip().lower()
            dataset_name = str(row.get("dataset_name") or "").strip()
            if dataset_id and (variant_id, dataset_id) not in lookup_by_id:
                lookup_by_id[(variant_id, dataset_id)] = row
            if dataset_name and (variant_id, dataset_name) not in lookup_by_name:
                lookup_by_name[(variant_id, dataset_name)] = row

        pick_map: dict[object, dict] = {}
        series_artist_map: dict[str, list] = {}
        centers = [float(i) for i in range(len(dataset_ids))]
        variant_count = max(1, len(selected_variants))
        total_width = 0.82
        bar_width = total_width / float(variant_count)

        for variant_idx, variant_id in enumerate(selected_variants):
            label = str(label_map.get(variant_id, variant_id))
            offset = (float(variant_idx) - (float(variant_count - 1) / 2.0)) * bar_width
            xs: list[float] = []
            ys: list[float] = []
            errs: list[float] = []
            rows_for_bars: list[dict] = []
            for dataset_idx, dataset_id in enumerate(dataset_ids):
                dataset_name = dataset_labels[dataset_idx] if dataset_idx < len(dataset_labels) else dataset_id
                row = lookup_by_id.get((variant_id, dataset_id))
                if row is None:
                    row = lookup_by_name.get((variant_id, dataset_name))
                if row is None:
                    continue
                y_val = row.get(y_key)
                if y_val is None:
                    continue
                xs.append(centers[dataset_idx] + offset)
                ys.append(float(y_val))
                errs.append(float(row.get(e_key) or 0.0))
                rows_for_bars.append(row)
            if not xs:
                continue
            bars = ax.bar(
                xs,
                ys,
                width=bar_width * 0.9,
                yerr=(errs if show_stddev else None),
                capsize=(3 if show_stddev else 0),
                label=label,
                align="center",
            )
            patches = list(getattr(bars, "patches", []) or [])
            if patches:
                series_artist_map[label] = patches
            for idx, rect in enumerate(patches):
                try:
                    rect.set_picker(True)
                except Exception:
                    pass
                row = rows_for_bars[idx] if idx < len(rows_for_bars) else None
                if row is None:
                    continue
                pick_map[rect] = {
                    "rows": [row],
                    "xs": [float(row.get("x_value", 0.0) or 0.0)],
                    "ys": [float(row.get(y_key, 0.0) or 0.0)],
                }

        ax.set_xticks(centers)
        ax.set_xticklabels(dataset_labels, rotation=25, ha="right")
        ax.set_xlabel("Dataset")
        if metric == "runtime":
            ax.set_ylabel("Runtime (ms)")
            ax.set_title("Runtime by Dataset")
        else:
            ax.set_ylabel("Peak Child Process Memory (KiB)")
            ax.set_title("Peak Child Process Memory by Dataset")
        if centers:
            ax.set_xlim(min(centers) - 0.6, max(centers) + 0.6)
        try:
            if use_log_y:
                ax.set_yscale("log")
        except Exception:
            pass
        ax.grid(True, axis="y", linestyle="--", linewidth=0.5, alpha=0.5)

        handles, legend_labels = ax.get_legend_handles_labels()
        legend_entry_map: dict[str, dict] = {}
        all_series_artists = []
        if handles:
            ncols = 1 if len(handles) <= 3 else 2
            legend_title = "Error bars: +/-1 SD" if show_stddev else None
            legend = ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, -0.22),
                ncol=ncols,
                fontsize=8,
                title=legend_title,
            )
            legend_texts = list(legend.get_texts())
            legend_handles = list(getattr(legend, "legend_handles", []) or getattr(legend, "legendHandles", []) or [])
            for idx, label in enumerate(legend_labels):
                data_artists = list(series_artist_map.get(label, []))
                if not data_artists:
                    continue
                legend_artists = []
                if idx < len(legend_handles):
                    legend_artists.append(legend_handles[idx])
                if idx < len(legend_texts):
                    legend_artists.append(legend_texts[idx])
                legend_entry_map[label] = {
                    "legend_artists": legend_artists,
                    "data_artists": data_artists,
                }
                all_series_artists.extend(data_artists)
            fig.tight_layout(rect=(0.0, 0.08, 1.0, 1.0))
        else:
            fig.tight_layout()

        if all_series_artists:
            deduped_all = []
            seen_ids: set[int] = set()
            for artist in all_series_artists:
                artist_id = id(artist)
                if artist_id in seen_ids:
                    continue
                seen_ids.add(artist_id)
                deduped_all.append(artist)
            setattr(
                fig,
                "_legend_hover_state",
                {
                    "entries": legend_entry_map,
                    "all_artists": deduped_all,
                    "active_label": None,
                },
            )
        else:
            setattr(fig, "_legend_hover_state", None)
        setattr(fig, "_drilldown_pick_map", pick_map)
        setattr(fig, "_drilldown_metric", metric)
        return fig

    def _make_metric_2d_figure(self, payload: dict, metric: str, datapoints: list[dict]):
        config = payload["run_config"]
        if str(config.get("input_mode") or "independent").strip().lower() == "datasets":
            return self._make_dataset_metric_bar_figure(payload, metric, datapoints)
        fig = Figure(figsize=(7.5, 5.0), dpi=100)
        ax = fig.add_subplot(111)
        primary_var = config["primary_variable"]
        secondary_var = config["secondary_variable"]
        x_values_full = list(config["var_ranges"].get(primary_var, []))

        selected_variants = config["selected_variants"]
        label_map = config["selected_variant_labels"]
        show_stddev = bool(self.show_stddev_var.get())
        show_regression = bool(self.show_regression_var.get())
        show_trendlines_only = bool(self.show_trendlines_only_var.get())
        effective_show_regression = show_regression or show_trendlines_only
        use_log_x = bool(self.log_x_scale_var.get())
        use_log_y = bool(self.log_y_scale_var.get())
        pick_map = {}
        series_artist_map: dict[str, list] = {}
        if not x_values_full:
            x_values_full = sorted({float(row["x_value"]) for row in datapoints if row["x_value"] is not None})
        point_lookup = {}
        for row in datapoints:
            variant_id = row.get("variant_id")
            x_val = row.get("x_value")
            y_val = row.get("y_value")
            if variant_id is None or x_val is None:
                continue
            point_lookup[(variant_id, float(x_val), None if y_val is None else float(y_val))] = row

        def plot_series(xs: list[float], ys: list[float], errs: list[float], label: str, rows: list[dict]):
            if not xs:
                return
            if use_log_x or use_log_y:
                filtered = [
                    (x, y, e, r)
                    for x, y, e, r in zip(xs, ys, errs, rows)
                    if ((not use_log_x) or x > 0) and ((not use_log_y) or y > 0)
                ]
                if not filtered:
                    return
                xs = [item[0] for item in filtered]
                ys = [item[1] for item in filtered]
                errs = [item[2] for item in filtered]
                rows = [item[3] for item in filtered]
            line_for_pick = None
            series_artists = []
            line_color = None
            if show_trendlines_only:
                reg_line = linear_regression_line(xs, ys)
                if reg_line is not None:
                    reg_x, reg_y = reg_line
                    reg_artist = ax.plot(
                        reg_x,
                        reg_y,
                        linestyle="--",
                        linewidth=1.4,
                        alpha=0.95,
                        label=label,
                    )[0]
                else:
                    reg_artist = ax.plot(
                        xs,
                        ys,
                        linestyle="--",
                        linewidth=1.4,
                        alpha=0.95,
                        label=label,
                    )[0]
                line_color = reg_artist.get_color()
                series_artists.append(reg_artist)
                pick_artist = ax.plot(
                    xs,
                    ys,
                    linestyle="None",
                    marker="o",
                    markersize=9.0,
                    alpha=0.0,
                    color=line_color,
                    label="_nolegend_",
                )[0]
                line_for_pick = pick_artist
                series_artists.append(pick_artist)
            else:
                if show_stddev:
                    container = ax.errorbar(xs, ys, yerr=errs, capsize=3, label=label)
                    if getattr(container, "lines", None):
                        first_line = container.lines[0]
                        line_color = first_line.get_color() if first_line is not None else None
                        line_for_pick = first_line
                    if line_for_pick is not None:
                        series_artists.append(line_for_pick)
                    try:
                        for item in list(getattr(container, "lines", [])[1:]):
                            if isinstance(item, (list, tuple)):
                                series_artists.extend([artist for artist in item if artist is not None])
                            elif item is not None:
                                series_artists.append(item)
                    except Exception:
                        pass
                else:
                    plotted = ax.plot(xs, ys, label=label)
                    line_color = plotted[0].get_color() if plotted else None
                    if plotted:
                        line_for_pick = plotted[0]
                        series_artists.append(line_for_pick)

            if line_for_pick is not None:
                try:
                    line_for_pick.set_picker(True)
                    line_for_pick.set_pickradius(8)
                    pick_map[line_for_pick] = {
                        "rows": list(rows),
                        "xs": list(xs),
                        "ys": list(ys),
                    }
                except Exception:
                    pass

            if effective_show_regression and not show_trendlines_only:
                reg_line = linear_regression_line(xs, ys)
                if reg_line is not None:
                    reg_x, reg_y = reg_line
                    reg_artist = ax.plot(
                        reg_x,
                        reg_y,
                        linestyle="--",
                        linewidth=1.2,
                        alpha=0.9,
                        color=line_color,
                        label="_nolegend_",
                    )[0]
                    series_artists.append(reg_artist)
            if series_artists:
                deduped = []
                seen_ids: set[int] = set()
                for artist in series_artists:
                    artist_id = id(artist)
                    if artist_id in seen_ids:
                        continue
                    seen_ids.add(artist_id)
                    deduped.append(artist)
                series_artist_map[label] = deduped

        if secondary_var is None:
            for variant_id in selected_variants:
                xs, ys, errs, rows = [], [], [], []
                for x in x_values_full:
                    match = point_lookup.get((variant_id, float(x), None))
                    if not match:
                        continue
                    y_key = "runtime_median_ms" if metric == "runtime" else "memory_median_kb"
                    e_key = "runtime_stdev_ms" if metric == "runtime" else "memory_stdev_kb"
                    y_val = match[y_key]
                    if y_val is None:
                        continue
                    xs.append(x)
                    ys.append(y_val)
                    errs.append(match[e_key] or 0.0)
                    rows.append(match)
                plot_series(xs, ys, errs, label_map.get(variant_id, variant_id), rows)
        else:
            y_values_full = list(config["var_ranges"].get(secondary_var, []))
            if not y_values_full:
                y_values_full = sorted({float(row["y_value"]) for row in datapoints if row["y_value"] is not None})
            for variant_id in selected_variants:
                for y_const in y_values_full:
                    xs, ys, errs, rows = [], [], [], []
                    for x in x_values_full:
                        match = point_lookup.get((variant_id, float(x), float(y_const)))
                        if not match:
                            continue
                        y_key = "runtime_median_ms" if metric == "runtime" else "memory_median_kb"
                        e_key = "runtime_stdev_ms" if metric == "runtime" else "memory_stdev_kb"
                        y_val = match[y_key]
                        if y_val is None:
                            continue
                        xs.append(x)
                        ys.append(y_val)
                        errs.append(match[e_key] or 0.0)
                        rows.append(match)
                    if xs:
                        series_name = (
                            f"{label_map.get(variant_id, variant_id)} | "
                            f"{self._axis_label(secondary_var, config)}={self._format_point_value(secondary_var, y_const, config)}"
                        )
                        plot_series(xs, ys, errs, series_name, rows)

        ax.set_xlabel(self._axis_label(primary_var, config))
        if metric == "runtime":
            ax.set_ylabel("Runtime (ms)")
            ax.set_title("Runtime by Independent Variable")
        else:
            ax.set_ylabel("Peak Child Process Memory (KiB)")
            ax.set_title("Peak Child Process Memory by Independent Variable")
        if x_values_full:
            ax.set_xlim(min(x_values_full), max(x_values_full))
        try:
            if use_log_x:
                ax.set_xscale("log")
            if use_log_y:
                ax.set_yscale("log")
        except Exception:
            pass
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)
        handles, legend_labels = ax.get_legend_handles_labels()
        legend_entry_map: dict[str, dict] = {}
        all_series_artists = []
        if handles:
            ncols = 1 if len(handles) <= 3 else 2
            legend_title = None
            if show_trendlines_only:
                legend_title = "Trendlines only"
            elif show_stddev and show_regression:
                legend_title = "Error bars: +/-1 SD | Dashed: linear trend"
            elif show_stddev:
                legend_title = "Error bars: +/-1 SD"
            elif show_regression:
                legend_title = "Dashed lines: linear trend"
            legend = ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, -0.22),
                ncol=ncols,
                fontsize=8,
                title=legend_title,
            )
            legend_texts = list(legend.get_texts())
            legend_handles = list(getattr(legend, "legend_handles", []) or getattr(legend, "legendHandles", []) or [])
            for idx, label in enumerate(legend_labels):
                data_artists = list(series_artist_map.get(label, []))
                if not data_artists:
                    continue
                legend_artists = []
                if idx < len(legend_handles):
                    legend_artists.append(legend_handles[idx])
                if idx < len(legend_texts):
                    legend_artists.append(legend_texts[idx])
                legend_entry_map[label] = {
                    "legend_artists": legend_artists,
                    "data_artists": data_artists,
                }
                all_series_artists.extend(data_artists)
            fig.tight_layout(rect=(0.0, 0.08, 1.0, 1.0))
        else:
            fig.tight_layout()
        if all_series_artists:
            deduped_all = []
            seen_ids: set[int] = set()
            for artist in all_series_artists:
                artist_id = id(artist)
                if artist_id in seen_ids:
                    continue
                seen_ids.add(artist_id)
                deduped_all.append(artist)
            setattr(
                fig,
                "_legend_hover_state",
                {
                    "entries": legend_entry_map,
                    "all_artists": deduped_all,
                    "active_label": None,
                },
            )
        else:
            setattr(fig, "_legend_hover_state", None)
        setattr(fig, "_drilldown_pick_map", pick_map)
        setattr(fig, "_drilldown_metric", metric)
        return fig

    def _build_3d_grid_for_variant(self, payload: dict, variant_id: str, metric: str, datapoints: list[dict]):
        config = payload["run_config"]
        primary_var = config["primary_variable"]
        secondary_var = config["secondary_variable"]
        if not secondary_var:
            return None
        xs = list(config["var_ranges"].get(primary_var, []))
        ys = list(config["var_ranges"].get(secondary_var, []))
        if not xs:
            xs = sorted({float(row["x_value"]) for row in datapoints if row["variant_id"] == variant_id and row["x_value"] is not None})
        if not ys:
            ys = sorted(
                {float(row["y_value"]) for row in datapoints if row["variant_id"] == variant_id and row["y_value"] is not None}
            )
        if not xs or not ys:
            return None
        z_grid = [[math.nan for _ in xs] for _ in ys]
        z_key = "runtime_median_ms" if metric == "runtime" else "memory_median_kb"
        x_index = {x: i for i, x in enumerate(xs)}
        y_index = {y: i for i, y in enumerate(ys)}
        for row in datapoints:
            if row["variant_id"] != variant_id:
                continue
            x = row["x_value"]
            y = row["y_value"]
            if y is None or x not in x_index or y not in y_index:
                continue
            z = row[z_key]
            if z is None:
                continue
            z_grid[y_index[y]][x_index[x]] = float(z)
        return xs, ys, z_grid

    def _make_metric_3d_figure(self, payload: dict, metric: str, datapoints: list[dict]):
        fig = Figure(figsize=(7.5, 5.0), dpi=100)
        ax = fig.add_subplot(111, projection="3d")
        config = payload["run_config"]
        secondary_var = config["secondary_variable"]
        if not secondary_var:
            ax.text2D(0.1, 0.5, "3D view requires two independent variables.", transform=ax.transAxes)
            fig.tight_layout()
            return fig

        selected_label = self.plot3d_variant_var.get().strip()
        label_to_id = {label: vid for vid, label in config["selected_variant_labels"].items()}
        variant_id = label_to_id.get(selected_label, config.get("plot3d_variant"))
        if not variant_id:
            ax.text2D(0.1, 0.5, "No selected variant available for 3D plotting.", transform=ax.transAxes)
            fig.tight_layout()
            return fig

        built = self._build_3d_grid_for_variant(payload, variant_id, metric, datapoints)
        if built is None:
            ax.text2D(0.1, 0.5, "No 3D data.", transform=ax.transAxes)
            fig.tight_layout()
            return fig
        xs, ys, z_grid = built
        style = self.plot3d_style_var.get().strip().lower()
        if style not in {"surface", "wireframe", "scatter"}:
            style = "surface"
        use_log_x = bool(self.log_x_scale_var.get())
        use_log_y = bool(self.log_y_scale_var.get())

        import numpy as np

        X, Y = np.meshgrid(xs, ys)
        Z = np.array(z_grid, dtype=float)

        if style == "surface":
            masked = np.ma.masked_invalid(Z)
            ax.plot_surface(X, Y, masked, cmap="viridis", edgecolor="black", linewidth=0.25, antialiased=True)
        elif style == "wireframe":
            masked = np.ma.masked_invalid(Z)
            ax.plot_wireframe(X, Y, masked, color="#1f77b4", linewidth=0.8)
        else:
            xv, yv, zv = [], [], []
            for yi, y in enumerate(ys):
                for xi, x in enumerate(xs):
                    z = z_grid[yi][xi]
                    if math.isfinite(z):
                        xv.append(x)
                        yv.append(y)
                        zv.append(z)
            ax.scatter(xv, yv, zv, c=zv if zv else None, cmap="viridis", depthshade=True)

        primary_var = config["primary_variable"]
        ax.set_xlabel(self._axis_label(primary_var, config))
        ax.set_ylabel(self._axis_label(secondary_var, config))
        if metric == "runtime":
            ax.set_zlabel("Runtime (ms)")
            ax.set_title(f"Runtime 3D ({config['selected_variant_labels'].get(variant_id, variant_id)})")
        else:
            ax.set_zlabel("Peak Memory (KiB)")
            ax.set_title(f"Memory 3D ({config['selected_variant_labels'].get(variant_id, variant_id)})")
        try:
            if use_log_x and xs and min(xs) > 0:
                ax.set_xscale("log")
            if use_log_y and ys and min(ys) > 0:
                ax.set_yscale("log")
        except Exception:
            pass
        ax.view_init(elev=DEFAULT_3D_ELEV, azim=DEFAULT_3D_AZIM)
        fig.tight_layout()
        return fig

    def _format_stats_number(self, value, decimals: int = 4) -> str:
        if value is None:
            return "n/a"
        try:
            numeric = float(value)
        except Exception:
            return "n/a"
        if not math.isfinite(numeric):
            return "n/a"
        return f"{numeric:.{int(max(0, decimals))}f}"

    def _stats_column_heading_map(self) -> dict[str, str]:
        return {
            "variant": "Variant",
            "baseline": "Baseline",
            "n": "n",
            "p_value": "p-value",
            "direction": "Direction",
            "mean_delta_ms": "Mean Delta (ms)",
            "ci95_ms": "95% CI Delta (ms)",
            "hedges_g": "Hedges g",
            "cliffs_delta": "Cliff's Delta",
            "mode": "Mode",
        }

    def _stats_sort_column_from_label(self, label: str) -> str | None:
        lookup = self._stats_column_heading_map()
        target = str(label or "").strip().lower()
        for col_id, heading in lookup.items():
            if str(heading).strip().lower() == target:
                return col_id
        return None

    def _stats_sort_key(self, column_id: str, values: tuple) -> tuple[bool, object]:
        if self.stats_tree is None:
            return True, ""
        columns = list(self.stats_tree.cget("columns") or [])
        try:
            idx = columns.index(column_id)
        except ValueError:
            return True, ""
        raw = values[idx] if idx < len(values) else ""
        text = str(raw or "").strip()
        if text == "" or text.lower() in {"n/a", "nan", "none"}:
            return True, ""

        numeric_cols = {"n", "p_value", "mean_delta_ms", "hedges_g", "cliffs_delta"}
        if column_id in numeric_cols:
            try:
                return False, float(text)
            except Exception:
                return True, ""
        if column_id == "ci95_ms":
            match = re.search(r"-?\d+(?:\.\d+)?", text)
            if match:
                try:
                    return False, float(match.group(0))
                except Exception:
                    pass
            return True, ""
        if column_id == "direction":
            order = {"faster": -1, "equal": 0, "slower": 1}
            return False, order.get(text.lower(), 99)
        return False, text.lower()

    def _sort_stats_tree(self, ascending: bool):
        tree = self.stats_tree
        if tree is None:
            return
        column_label = self.stats_sort_column_var.get().strip()
        col_id = self._stats_sort_column_from_label(column_label)
        if not col_id:
            return
        rows = []
        for item_id in tree.get_children(""):
            values = tuple(tree.item(item_id, "values") or ())
            missing, sort_value = self._stats_sort_key(col_id, values)
            rows.append((item_id, missing, sort_value))
        if not rows:
            return

        present = [row for row in rows if not row[1]]
        missing = [row for row in rows if row[1]]
        present.sort(key=lambda row: row[2], reverse=not bool(ascending))
        ordered = present + missing
        for idx, row in enumerate(ordered):
            tree.move(row[0], "", idx)

    def _clear_stats_table(self):
        if self.stats_tree is None:
            return
        try:
            for item in self.stats_tree.get_children():
                self.stats_tree.delete(item)
        except Exception:
            pass
        try:
            self.stats_blurb_var.set("Run a benchmark to populate runtime statistical comparisons.")
            self.stats_summary_var.set("No statistical comparisons available yet.")
        except Exception:
            pass

    def _close_stats_help_popup(self):
        popup = self.stats_help_popup
        self.stats_help_popup = None
        if popup is not None:
            try:
                popup.destroy()
            except Exception:
                pass

    def _stats_heading_help_text(self, column_id: str) -> tuple[str, str]:
        key = str(column_id or "").strip().lower()
        if key == "variant":
            return ("Variant", "The solver implementation being evaluated in this row.")
        if key == "baseline":
            return ("Baseline", "The benchmark solver this variant is compared against for runtime deltas.")
        if key == "n":
            return (
                "n (Matched Samples)",
                "The number of iteration pairs where both variant and baseline produced a runtime.",
            )
        if key == "p_value":
            return (
                "p-value",
                "Two-sided paired t-test p-value. Smaller values indicate stronger evidence of a real mean runtime difference.",
            )
        if key == "direction":
            return (
                "Direction",
                "Interprets mean delta sign for variant - baseline. "
                "'faster' means negative delta; 'slower' means positive delta.",
            )
        if key == "mean_delta_ms":
            return (
                "Mean Delta (ms)",
                "Average runtime difference computed as variant - baseline in milliseconds.",
            )
        if key == "ci95_ms":
            return (
                "95% CI Delta (ms)",
                "Approximate 95% confidence interval for the mean runtime delta (variant - baseline).",
            )
        if key == "hedges_g":
            return (
                "Hedges g",
                "Bias-corrected standardized effect size for paired deltas. Larger absolute values indicate stronger effects.",
            )
        if key == "cliffs_delta":
            return (
                "Cliff's Delta",
                "Non-parametric effect size from -1 to +1 measuring distribution dominance between variant and baseline runtimes.",
            )
        if key == "mode":
            return (
                "Mode",
                "Timing phase being compared. 'single' is one-shot timing; other families may provide first/all modes.",
            )
        return ("Column Help", "No description is available for this column.")

    def _show_stats_heading_help(self, column_id: str):
        title, body = self._stats_heading_help_text(column_id)
        self._close_stats_help_popup()
        popup = tk.Toplevel(self)
        popup.title("Column Help")
        try:
            popup.transient(self)
        except Exception:
            pass
        popup.resizable(False, False)
        popup.protocol("WM_DELETE_WINDOW", self._close_stats_help_popup)
        self.stats_help_popup = popup

        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        header = ttk.Frame(frame)
        header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(header, text=title, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="X", width=3, command=self._close_stats_help_popup).pack(side=tk.RIGHT)
        ttk.Label(
            frame,
            text=body,
            justify=tk.LEFT,
            wraplength=360,
        ).pack(fill=tk.X, anchor="w")

        try:
            popup.update_idletasks()
            x = int(self.winfo_pointerx()) + 14
            y = int(self.winfo_pointery()) + 14
            screen_w = int(self.winfo_screenwidth() or 1200)
            screen_h = int(self.winfo_screenheight() or 800)
            w = int(popup.winfo_reqwidth() or 380)
            h = int(popup.winfo_reqheight() or 120)
            x = max(8, min(x, max(8, screen_w - w - 8)))
            y = max(8, min(y, max(8, screen_h - h - 8)))
            popup.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _render_statistical_tests_panel(self, payload: dict):
        if self.stats_tree is None:
            return
        self._clear_stats_table()
        stats_block = payload.get("statistical_tests") if isinstance(payload, dict) else None
        if not isinstance(stats_block, dict):
            self.stats_summary_var.set("This payload does not include a statistical_tests section.")
            return

        alpha_raw = stats_block.get("alpha")
        alpha_text = self._format_stats_number(alpha_raw, decimals=3) if alpha_raw is not None else "0.050"
        self.stats_blurb_var.set(
            "Runtime comparisons are measured as variant - baseline. "
            "Negative mean delta means the variant is faster; positive means slower."
        )

        rows = [row for row in list(stats_block.get("pairs") or []) if isinstance(row, dict)]
        if not rows:
            self.stats_summary_var.set(
                f"No pairwise comparisons were recorded for this run (alpha={alpha_text})."
            )
            return

        rows.sort(key=lambda row: (str(row.get("variant_label") or row.get("variant_id") or ""), str(row.get("mode") or "")))
        significant_count = 0
        inserted_count = 0
        for row in rows:
            variant_label = str(row.get("variant_label") or row.get("variant_id") or "variant")
            baseline_label = str(row.get("baseline_label") or row.get("baseline_variant_id") or "baseline")
            mode = str(row.get("mode") or "single")
            n = int(row.get("n") or 0)

            paired = row.get("paired_t_test")
            paired = paired if isinstance(paired, dict) else {}
            effects = row.get("effect_sizes")
            effects = effects if isinstance(effects, dict) else {}
            ci = row.get("delta_ci_95_ms")
            ci = ci if isinstance(ci, dict) else {}

            p_value = paired.get("p_value_two_sided")
            ci_low = ci.get("low")
            ci_high = ci.get("high")
            ci_text = f"[{self._format_stats_number(ci_low, 3)}, {self._format_stats_number(ci_high, 3)}]"
            significant = bool(row.get("significant_at_alpha"))
            if significant:
                significant_count += 1

            direction = str(row.get("direction") or "n/a")
            tags = ()
            if significant:
                tags = ("significant",)
            elif n < 2:
                tags = ("insufficient",)

            self.stats_tree.insert(
                "",
                tk.END,
                values=(
                    variant_label,
                    baseline_label,
                    str(n),
                    self._format_stats_number(p_value, 6),
                    direction,
                    self._format_stats_number(row.get("mean_delta_ms"), 3),
                    ci_text,
                    self._format_stats_number(effects.get("hedges_g"), 4),
                    self._format_stats_number(effects.get("cliffs_delta"), 4),
                    mode,
                ),
                tags=tags,
            )
            inserted_count += 1

        self.stats_summary_var.set(
            f"Comparisons: {inserted_count} | significant (p < {alpha_text}): {significant_count}."
        )
        self._refresh_stats_blurb_wraplength()

    def _render_plots(self, payload: dict):
        self._clear_drilldown()
        datapoints = self._collect_payload_datapoints(payload)
        runtime_fig = self._make_metric_2d_figure(payload, metric="runtime", datapoints=datapoints)
        memory_fig = self._make_metric_2d_figure(payload, metric="memory", datapoints=datapoints)
        runtime_3d_fig = self._make_metric_3d_figure(payload, metric="runtime", datapoints=datapoints)
        memory_3d_fig = self._make_metric_3d_figure(payload, metric="memory", datapoints=datapoints)

        self.runtime_canvas = self._render_figure_in_frame(
            self.runtime_frame,
            runtime_fig,
            self.runtime_canvas,
            motion_handler=lambda event: self._on_2d_motion(event, metric="runtime"),
            click_handler=lambda event: self._on_2d_click(event, metric="runtime"),
            leave_handler=lambda event: self._on_2d_leave(event, metric="runtime"),
        )
        self.memory_canvas = self._render_figure_in_frame(
            self.memory_frame,
            memory_fig,
            self.memory_canvas,
            motion_handler=lambda event: self._on_2d_motion(event, metric="memory"),
            click_handler=lambda event: self._on_2d_click(event, metric="memory"),
            leave_handler=lambda event: self._on_2d_leave(event, metric="memory"),
        )
        self.runtime_3d_canvas = self._render_figure_in_frame(self.runtime_3d_frame, runtime_3d_fig, self.runtime_3d_canvas)
        self.memory_3d_canvas = self._render_figure_in_frame(self.memory_3d_frame, memory_3d_fig, self.memory_3d_canvas)

        self.last_runtime_fig = runtime_fig
        self.last_memory_fig = memory_fig
        self.last_runtime_3d_fig = runtime_3d_fig
        self.last_memory_3d_fig = memory_3d_fig
        self._render_statistical_tests_panel(payload)

    def _repaint_existing_plots(self):
        if not self.last_plot_context:
            return
        self._render_plots(self.last_plot_context)

    def _apply_legend_hover_focus(self, figure, active_label: str | None):
        if figure is None:
            return
        state = getattr(figure, "_legend_hover_state", None)
        if not isinstance(state, dict):
            return
        entries = state.get("entries", {})
        if not isinstance(entries, dict) or not entries:
            return
        if state.get("active_label") == active_label:
            return

        visible_artists = set()
        if active_label is not None:
            entry = entries.get(active_label, {})
            if isinstance(entry, dict):
                visible_artists = {artist for artist in entry.get("data_artists", []) if artist is not None}

        for artist in list(state.get("all_artists", [])):
            try:
                artist.set_visible(active_label is None or artist in visible_artists)
            except Exception:
                pass
        state["active_label"] = active_label
        canvas = getattr(figure, "canvas", None)
        if canvas is not None:
            try:
                canvas.draw_idle()
            except Exception:
                pass

    def _update_legend_hover(self, event) -> bool:
        canvas = getattr(event, "canvas", None)
        figure = getattr(canvas, "figure", None)
        if figure is None:
            return False
        state = getattr(figure, "_legend_hover_state", None)
        if not isinstance(state, dict):
            return False
        entries = state.get("entries", {})
        if not isinstance(entries, dict) or not entries:
            return False

        hovered_label = None
        for label, payload in entries.items():
            legend_artists = list(payload.get("legend_artists", [])) if isinstance(payload, dict) else []
            for legend_artist in legend_artists:
                try:
                    contains, _ = legend_artist.contains(event)
                except Exception:
                    contains = False
                if contains:
                    hovered_label = str(label)
                    break
            if hovered_label is not None:
                break

        self._apply_legend_hover_focus(figure, hovered_label)
        return hovered_label is not None

    def _locate_2d_row_from_event(self, event, metric: str):
        if event is None or getattr(event, "inaxes", None) is None:
            return None
        fig = getattr(event, "canvas", None)
        if fig is None:
            return None
        figure = getattr(fig, "figure", None)
        pick_map = getattr(figure, "_drilldown_pick_map", {}) if figure is not None else {}
        for artist, payload in pick_map.items():
            try:
                if getattr(artist, "axes", None) is not event.inaxes:
                    continue
                contains, info = artist.contains(event)
            except Exception:
                continue
            if not contains:
                continue
            inds = list((info or {}).get("ind", []) or [])
            rows = list(payload.get("rows", []))
            xs = list(payload.get("xs", []))
            ys = list(payload.get("ys", []))
            if not inds:
                if len(rows) == 1:
                    idx = 0
                else:
                    continue
            else:
                idx = int(inds[0])
            if idx < 0 or idx >= len(rows):
                continue
            x_val = float(xs[idx]) if idx < len(xs) else float(rows[idx].get("x_value", 0.0))
            y_val = float(ys[idx]) if idx < len(ys) else float(rows[idx].get("runtime_median_ms", 0.0))
            return {
                "metric": metric,
                "row": rows[idx],
                "x": x_val,
                "y": y_val,
                "ax": event.inaxes,
                "canvas": event.canvas,
            }
        return None

    def _place_popup_near_pointer(self, popup: tk.Toplevel, x_root: int, y_root: int, offset_x: int = 16, offset_y: int = 16):
        try:
            popup.update_idletasks()
            popup_width = int(popup.winfo_width() or popup.winfo_reqwidth() or 1)
            popup_height = int(popup.winfo_height() or popup.winfo_reqheight() or 1)
            screen_width = int(self.winfo_screenwidth() or 1)
            screen_height = int(self.winfo_screenheight() or 1)
            margin = 12
            x_pos = int(x_root + offset_x)
            y_pos = int(y_root + offset_y)
            if x_pos + popup_width + margin > screen_width:
                x_pos = int(x_root - popup_width - offset_x)
            if y_pos + popup_height + margin > screen_height:
                y_pos = int(y_root - popup_height - offset_y)
            x_pos = max(margin, min(x_pos, max(margin, screen_width - popup_width - margin)))
            y_pos = max(margin, min(y_pos, max(margin, screen_height - popup_height - margin)))
            popup.geometry(f"+{x_pos}+{y_pos}")
        except Exception:
            try:
                popup.geometry(f"+{int(x_root + offset_x)}+{int(y_root + offset_y)}")
            except Exception:
                pass

    def _drilldown_pointer_position(self, event):
        gui_event = getattr(event, "guiEvent", None)
        if gui_event is not None:
            x_root = getattr(gui_event, "x_root", None)
            y_root = getattr(gui_event, "y_root", None)
            if x_root is not None and y_root is not None:
                return int(x_root), int(y_root)
        try:
            return self.winfo_pointerx(), self.winfo_pointery()
        except Exception:
            return 100, 100

    def _open_drilldown_popup(self, info: dict, mode: str, event):
        row = info["row"]
        metric = info["metric"]
        key = self._drilldown_point_key(metric, row)
        text = self._drilldown_text_for_row(row, metric)
        x_root, y_root = self._drilldown_pointer_position(event)
        palette = self._theme_palette()

        if mode == "hover" and self.drilldown_popup_mode == "click":
            return

        if mode == "hover" and self.drilldown_popup_mode == "hover" and self.drilldown_popup_point_key == key and self.drilldown_popup is not None:
            self._place_popup_near_pointer(self.drilldown_popup, x_root, y_root, offset_x=16, offset_y=16)
            return

        self._clear_drilldown()

        if mode == "hover":
            popup = tk.Toplevel(self)
            popup.overrideredirect(True)
            popup.attributes("-topmost", True)
            label = tk.Label(
                popup,
                text=text,
                justify=tk.LEFT,
                anchor="w",
                bg=palette["tooltip_bg"],
                fg=palette["tooltip_fg"],
                relief="solid",
                bd=1,
                padx=8,
                pady=6,
                font=("Consolas", 9),
            )
            label.pack(fill=tk.BOTH, expand=True)
            self._place_popup_near_pointer(popup, x_root, y_root, offset_x=16, offset_y=16)
        else:
            popup = tk.Toplevel(self)
            popup.title("Datapoint Drilldown")
            popup.attributes("-topmost", True)

            def _close_click_popup():
                self._clear_drilldown()

            popup.protocol("WM_DELETE_WINDOW", _close_click_popup)
            header = ttk.Frame(popup)
            header.pack(fill=tk.X, padx=8, pady=(8, 4))
            ttk.Label(header, text="Datapoint Drilldown", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
            ttk.Button(header, text="X", width=3, command=_close_click_popup).pack(side=tk.RIGHT)
            body = ScrolledText(popup, height=16, wrap=tk.WORD)
            body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
            body.insert("1.0", text)
            try:
                body.configure(
                    bg=palette["text_bg"],
                    fg=palette["text_fg"],
                    insertbackground=palette["text_fg"],
                    selectbackground=palette["select_bg"],
                    selectforeground=palette["select_fg"],
                )
            except Exception:
                pass
            body.configure(state=tk.DISABLED)
            self._place_popup_near_pointer(popup, x_root, y_root, offset_x=20, offset_y=20)

        self.drilldown_popup = popup
        self.drilldown_popup_mode = mode
        self.drilldown_popup_point_key = key
        self._set_drilldown_highlight(info["ax"], info["canvas"], info["x"], info["y"])

    def _on_2d_motion(self, event, metric: str):
        if self.drilldown_popup_mode == "click":
            return
        if self._update_legend_hover(event):
            if self.drilldown_popup_mode == "hover":
                self._clear_drilldown()
            return
        info = self._locate_2d_row_from_event(event, metric)
        if info is None:
            if self.drilldown_popup_mode == "hover":
                self._clear_drilldown()
            return
        self._open_drilldown_popup(info, mode="hover", event=event)

    def _on_2d_leave(self, _event, metric: str):
        figure = getattr(getattr(_event, "canvas", None), "figure", None)
        if figure is not None:
            self._apply_legend_hover_focus(figure, None)
        if metric and self.drilldown_popup_mode == "hover":
            self._clear_drilldown()

    def _on_2d_click(self, event, metric: str):
        if int(getattr(event, "button", 0) or 0) != 1:
            return
        info = self._locate_2d_row_from_event(event, metric)
        if info is None:
            return
        key = self._drilldown_point_key(metric, info["row"])
        if self.drilldown_popup_mode == "click" and self.drilldown_popup_point_key == key:
            self._clear_drilldown()
            return
        self._open_drilldown_popup(info, mode="click", event=event)

    def _refresh_visualizer_controls(self, payload: dict):
        run_config = payload.get("run_config")
        if not isinstance(run_config, dict):
            self._reset_visualizer_selection_state()
            self._clear_visualizer_render()
            return

        family, _view_label, _algo = self._visualizer_family_context(run_config)
        rows_with_index = self._collect_visualizer_point_rows(payload, family)
        old_selected = self._selected_visualizer_point(run_config)
        self.visualizer_point_rows = []
        for item in rows_with_index:
            row = item.get("row") or {}
            point = self._resolve_visualizer_point_from_row(run_config, row, family)
            if not point:
                continue
            self.visualizer_point_rows.append({**item, "point": point, "point_key": self._visualizer_point_key(point)})

        vars_for_tab = self._visualizer_vars_for_tab(run_config)
        for var_id in ("n", "k", "density"):
            raw_values: list[float] = []
            for item in self.visualizer_point_rows:
                point = item.get("point") or {}
                raw = point.get(var_id)
                if isinstance(raw, (int, float)):
                    raw_values.append(float(raw))
            unique_values = sorted({float(v) for v in raw_values})
            if not unique_values:
                fixed_raw = run_config.get("fixed_values", {}).get(var_id)
                if isinstance(fixed_raw, (int, float)):
                    unique_values = [float(fixed_raw)]
                else:
                    range_values = run_config.get("var_ranges", {}).get(var_id, [])
                    if isinstance(range_values, list) and range_values:
                        try:
                            unique_values = [float(range_values[0])]
                        except Exception:
                            unique_values = []
            self.visualizer_nav_values[var_id] = unique_values
            self.visualizer_nav_index[var_id] = 0
            if old_selected and var_id in vars_for_tab and unique_values:
                try:
                    target = float(old_selected.get(var_id))
                except Exception:
                    target = None
                if target is not None:
                    best_idx = min(range(len(unique_values)), key=lambda idx: abs(unique_values[idx] - target))
                    if abs(unique_values[best_idx] - target) <= 1e-9:
                        self.visualizer_nav_index[var_id] = int(best_idx)

        self._update_visualizer_nav_controls(run_config)
        if not self.visualizer_point_rows:
            self.visualizer_status_var.set("No visualizer datapoints were recorded for this run.")
        else:
            self.visualizer_status_var.set("Ready. Choose a datapoint tuple and click Load In Tab.")

    def _collect_visualizer_point_rows(self, payload: dict, family: str) -> list[dict]:
        datapoints = self._collect_payload_datapoints(payload)
        if not datapoints:
            return []
        run_config = payload.get("run_config")
        if not isinstance(run_config, dict):
            return []
        baseline_id = f"{family}_baseline"
        rows = [
            row for row in datapoints
            if str(row.get("variant_id") or "").strip().lower() == baseline_id
        ]
        if not rows:
            rows = [
                row for row in datapoints
                if str(row.get("variant_id") or "").strip().lower().startswith(f"{family}_")
            ]
        out: list[dict] = []
        for row in rows:
            point_idx = self._find_datapoint_index_from_run_config(run_config, row)
            out.append({"row": row, "point_idx": point_idx})
        out.sort(
            key=lambda item: (
                float(item["row"]["x_value"]) if isinstance(item.get("row", {}).get("x_value"), (int, float)) else float("inf"),
                float(item["row"]["y_value"]) if isinstance(item.get("row", {}).get("y_value"), (int, float)) else float("-inf"),
            )
        )
        return out

    def _reset_visualizer_selection_state(self):
        self.visualizer_point_rows = []
        self.visualizer_nav_values = {"n": [], "k": [], "density": []}
        self.visualizer_nav_index = {"n": 0, "k": 0, "density": 0}
        self.visualizer_loaded_result = None
        self.visualizer_active_context_key = None
        self.visualizer_iterations = []
        self.visualizer_iteration_index = 0
        self.visualizer_solution_index = 0
        self.visualizer_iteration_label_var.set("Iteration --")
        self.visualizer_solution_label_var.set("Solution --")
        self.visualizer_solution_count_var.set("Solution Count: --")
        self.visualizer_no_solution_var.set("")
        self._deactivate_visualizer_autoplay(reset_last_key=True)
        if self.last_run_payload and isinstance(self.last_run_payload, dict):
            run_cfg = self.last_run_payload.get("run_config")
        else:
            run_cfg = None
        self._update_visualizer_nav_controls(run_cfg if isinstance(run_cfg, dict) else None)
        self._update_visualizer_iteration_solution_controls()

    def _clear_visualizer_render(self):
        if self.visualizer_graph_canvas is not None:
            try:
                self.visualizer_graph_canvas.get_tk_widget().destroy()
            except Exception:
                pass
            self.visualizer_graph_canvas = None
        if self.visualizer_graph_fig is not None:
            try:
                self.visualizer_graph_fig.clear()
            except Exception:
                pass
            self.visualizer_graph_fig = None
        self.visualizer_iterations = []
        self.visualizer_iteration_index = 0
        self.visualizer_solution_index = 0
        self.visualizer_iteration_label_var.set("Iteration --")
        self.visualizer_solution_label_var.set("Solution --")
        self.visualizer_solution_count_var.set("Solution Count: --")
        self.visualizer_no_solution_var.set("")
        self._update_visualizer_iteration_solution_controls()
        self._refresh_visualizer_host_scrollregion()
        self._refresh_visualizer_fullscreen_canvas()

    def _visualizer_vars_for_tab(self, run_config: dict) -> list[str]:
        tab_id = str(run_config.get("tab_id") or "").strip().lower()
        if tab_id == "subgraph":
            return ["n", "k", "density"]
        return ["n", "density"]

    def _visualizer_point_key(self, point: dict) -> tuple[float, float, float]:
        return (
            round(float(point.get("n", math.nan)), 10),
            round(float(point.get("k", math.nan)), 10),
            round(float(point.get("density", math.nan)), 10),
        )

    def _resolve_visualizer_point_from_row(self, run_config: dict, row: dict, family: str) -> dict | None:
        primary = str(run_config.get("primary_variable") or "").strip()
        secondary = str(run_config.get("secondary_variable") or "").strip() or None
        fixed_raw = run_config.get("fixed_values")
        fixed_values = dict(fixed_raw) if isinstance(fixed_raw, dict) else {}

        point: dict[str, float] = {}
        for k, v in fixed_values.items():
            try:
                point[str(k)] = float(v)
            except Exception:
                continue

        if primary:
            x_val = row.get("x_value")
            if isinstance(x_val, (int, float)):
                point[primary] = float(x_val)
        if secondary:
            y_val = row.get("y_value")
            if isinstance(y_val, (int, float)):
                point[secondary] = float(y_val)

        for required_key in ("n", "density", "k"):
            if required_key in point:
                continue
            vals = run_config.get("var_ranges", {}).get(required_key, [])
            if isinstance(vals, list) and vals:
                try:
                    point[required_key] = float(vals[0])
                except Exception:
                    pass

        if "n" not in point or "density" not in point:
            return None

        if family not in {"dijkstra", "sp_via"}:
            if "k" not in point:
                return None
            n_nodes = int(round(float(point["n"])))
            k_mode = str(run_config.get("k_mode") or "percent").strip().lower()
            if k_mode == "absolute":
                k_nodes = int(round(float(point["k"])))
            else:
                k_nodes = int(round((float(point["k"]) / 100.0) * n_nodes))
                k_nodes = max(2, min(n_nodes - 1, k_nodes))
            if k_nodes < 2:
                k_nodes = 2
            if k_nodes >= n_nodes:
                k_nodes = max(2, n_nodes - 1)
            point["k_nodes"] = float(k_nodes)

        return point

    def _update_visualizer_nav_controls(self, run_config: dict | None):
        vars_for_tab = self._visualizer_vars_for_tab(run_config) if isinstance(run_config, dict) else []
        for var_id in ("n", "k", "density"):
            row = self.visualizer_nav_rows.get(var_id)
            if row is None:
                continue
            name_label = self.visualizer_nav_name_labels.get(var_id)
            if name_label is not None and isinstance(run_config, dict):
                try:
                    name_label.configure(text=f"{self._axis_label(var_id, run_config)}:")
                except Exception:
                    pass
            if var_id in vars_for_tab:
                if not row.winfo_manager():
                    row.pack(fill=tk.X, pady=(1, 1))
            else:
                if row.winfo_manager():
                    row.pack_forget()
                continue

            values = self.visualizer_nav_values.get(var_id, [])
            idx = int(self.visualizer_nav_index.get(var_id, 0))
            if values:
                idx = max(0, min(idx, len(values) - 1))
                self.visualizer_nav_index[var_id] = idx
                value = values[idx]
                display = self._format_point_value(var_id, float(value), run_config)
                self.visualizer_nav_display_vars[var_id].set(display)
                self.visualizer_nav_count_vars[var_id].set(f"({idx + 1}/{len(values)})")
            else:
                self.visualizer_nav_index[var_id] = 0
                self.visualizer_nav_display_vars[var_id].set("--")
                self.visualizer_nav_count_vars[var_id].set("(0/0)")

            enabled = (len(values) > 1) and (not self.visualizer_is_loading)
            jump_buttons = self.visualizer_nav_jump_buttons.get(var_id, {})
            for delta, button in jump_buttons.items():
                target = idx + int(delta)
                valid = enabled and 0 <= target < len(values)
                button.configure(state=(tk.NORMAL if valid else tk.DISABLED))
            value_widget = self.visualizer_nav_value_labels.get(var_id)
            if value_widget is not None:
                try:
                    palette = self._theme_palette()
                    value_widget.configure(
                        fg=(palette["value_active_fg"] if len(values) > 1 else palette["value_disabled_fg"])
                    )
                except Exception:
                    pass
        self._sync_visualizer_fullscreen_controls(run_config)
        self._update_visualizer_autoplay_controls()

    def _selected_visualizer_point(self, run_config: dict | None = None) -> dict[str, float] | None:
        if run_config is None:
            payload = self.last_run_payload if isinstance(self.last_run_payload, dict) else {}
            cfg = payload.get("run_config")
            run_config = cfg if isinstance(cfg, dict) else None
        if not isinstance(run_config, dict):
            return None
        vars_for_tab = self._visualizer_vars_for_tab(run_config)
        point: dict[str, float] = {}
        for var_id in vars_for_tab:
            values = self.visualizer_nav_values.get(var_id, [])
            if not values:
                return None
            idx = max(0, min(int(self.visualizer_nav_index.get(var_id, 0)), len(values) - 1))
            point[var_id] = float(values[idx])
        return point

    def _find_visualizer_item_for_selected_point(self, selected_point: dict[str, float]) -> dict | None:
        tol = 1e-9
        for item in self.visualizer_point_rows:
            point = item.get("point") or {}
            matched = True
            for key, target in selected_point.items():
                raw = point.get(key)
                if not isinstance(raw, (int, float)) or abs(float(raw) - float(target)) > tol:
                    matched = False
                    break
            if matched:
                return item
        return None

    def _visualizer_available_autoplay_keys(self, run_config: dict | None = None) -> list[str]:
        if run_config is None and isinstance(self.last_run_payload, dict):
            raw = self.last_run_payload.get("run_config")
            run_config = raw if isinstance(raw, dict) else None
        vars_for_tab = self._visualizer_vars_for_tab(run_config) if isinstance(run_config, dict) else []
        out: list[str] = []
        if "n" in vars_for_tab:
            out.append("var_n")
        if "k" in vars_for_tab:
            out.append("var_k")
        if "density" in vars_for_tab:
            out.append("var_density")
        out.append("iteration")
        out.append("solution")
        return out

    def _visualizer_autoplay_range(self, key: str) -> int:
        if key.startswith("var_"):
            var_id = key[4:]
            return len(self.visualizer_nav_values.get(var_id, []))
        if key == "iteration":
            return len(self.visualizer_iterations)
        if key == "solution":
            return len(self._current_visualizer_solutions())
        return 0

    def _visualizer_autoplay_index(self, key: str) -> int:
        if key.startswith("var_"):
            var_id = key[4:]
            return int(self.visualizer_nav_index.get(var_id, 0))
        if key == "iteration":
            return int(self.visualizer_iteration_index)
        if key == "solution":
            return int(self.visualizer_solution_index)
        return 0

    def _visualizer_ordered_autoplay_candidates(self) -> list[str]:
        run_cfg = self.last_run_payload.get("run_config") if isinstance(self.last_run_payload, dict) else None
        available = set(self._visualizer_available_autoplay_keys(run_cfg if isinstance(run_cfg, dict) else None))
        active = [
            key
            for key, enabled in self.visualizer_autoplay_active.items()
            if enabled and key in available and self._visualizer_autoplay_range(key) > 1
        ]
        if not active:
            return []
        out: list[str] = []
        if "solution" in active:
            out.append("solution")
            active.remove("solution")
        if "iteration" in active:
            out.append("iteration")
            active.remove("iteration")
        active.sort(key=lambda k: (self._visualizer_autoplay_range(k), k))
        out.extend(active)
        return out

    def _visualizer_select_next_autoplay_key(self) -> str | None:
        ordered = self._visualizer_ordered_autoplay_candidates()
        if not ordered:
            return None
        last = self.visualizer_autoplay_last_key
        if last in ordered:
            idx = ordered.index(last)
            return ordered[(idx + 1) % len(ordered)]
        return ordered[0]

    def _visualizer_step_forward_autoplay(self, key: str) -> tuple[bool, bool]:
        total = self._visualizer_autoplay_range(key)
        if total <= 1:
            return False, False
        old = self._visualizer_autoplay_index(key)
        new = (old + 1) % total
        wrapped = bool(new <= old)
        if key.startswith("var_"):
            if self.visualizer_is_loading:
                return False, False
            var_id = key[4:]
            self.visualizer_nav_index[var_id] = int(new)
            run_config = self.last_run_payload.get("run_config") if isinstance(self.last_run_payload, dict) else None
            self._update_visualizer_nav_controls(run_config if isinstance(run_config, dict) else None)
            self._on_visualizer_variable_changed()
            return True, wrapped
        if key == "iteration":
            self.visualizer_iteration_index = int(new)
            self.visualizer_solution_index = 0
            self._render_visualizer_current_iteration()
            return True, wrapped
        if key == "solution":
            self.visualizer_solution_index = int(new)
            self._render_visualizer_current_iteration()
            return True, wrapped
        return False, False

    def _start_visualizer_autoplay_timer(self):
        if self.visualizer_autoplay_after_id is None:
            self.visualizer_autoplay_after_id = self.after(500, self._visualizer_autoplay_tick)

    def _stop_visualizer_autoplay_timer(self):
        if self.visualizer_autoplay_after_id is not None:
            try:
                self.after_cancel(self.visualizer_autoplay_after_id)
            except Exception:
                pass
            self.visualizer_autoplay_after_id = None

    def _visualizer_autoplay_tick(self):
        self.visualizer_autoplay_after_id = None
        if not any(self.visualizer_autoplay_active.values()):
            self.visualizer_autoplay_current_key = None
            self.visualizer_autoplay_cycle_start_index = None
            self.visualizer_autoplay_cycle_steps = 0
            self._update_visualizer_autoplay_controls()
            return

        if self.visualizer_is_loading:
            self._update_visualizer_autoplay_controls()
            if any(self.visualizer_autoplay_active.values()):
                self._start_visualizer_autoplay_timer()
            return

        ordered = self._visualizer_ordered_autoplay_candidates()
        self.visualizer_autoplay_current_key = None
        self.visualizer_autoplay_cycle_start_index = None
        self.visualizer_autoplay_cycle_steps = 0
        self.visualizer_autoplay_last_key = None
        if ordered:
            # Nested carry model:
            # solution increments every tick; iteration increments only when
            # solution wraps; variables increment only when all higher-priority
            # keys wrap in that same tick.
            carry = True
            for key in ordered:
                if not carry:
                    break
                moved, wrapped = self._visualizer_step_forward_autoplay(key)
                if not moved:
                    break
                carry = bool(wrapped)

        self._update_visualizer_autoplay_controls()
        if any(self.visualizer_autoplay_active.values()):
            self._start_visualizer_autoplay_timer()

    def _update_visualizer_autoplay_controls(self):
        run_cfg = self.last_run_payload.get("run_config") if isinstance(self.last_run_payload, dict) else None
        available = set(self._visualizer_available_autoplay_keys(run_cfg if isinstance(run_cfg, dict) else None))

        def _apply_button_state(btn, enabled: bool):
            if btn is not None:
                btn.configure(state=(tk.NORMAL if enabled else tk.DISABLED))

        for key in self.visualizer_autoplay_keys:
            active = bool(self.visualizer_autoplay_active.get(key))
            var = self.visualizer_autoplay_label_vars.get(key)
            if var is not None:
                var.set("Pause" if active else "Play")
            rng = self._visualizer_autoplay_range(key)
            is_available = key in available
            enabled = bool(active or (is_available and rng > 1))
            if key.startswith("var_"):
                v = key[4:]
                _apply_button_state(self.visualizer_nav_play_buttons.get(v), enabled)
                _apply_button_state(self.visualizer_fullscreen_nav_play_buttons.get(v), enabled)
            elif key == "iteration":
                _apply_button_state(self.visualizer_iter_play_btn, enabled)
                _apply_button_state(self.visualizer_fullscreen_iter_play_btn, enabled)
            elif key == "solution":
                _apply_button_state(self.visualizer_sol_play_btn, enabled)
                _apply_button_state(self.visualizer_fullscreen_sol_play_btn, enabled)

        any_active = any(self.visualizer_autoplay_active.values())
        global_enabled = bool(self.last_run_payload and self.visualizer_point_rows)
        self.visualizer_autoplay_global_label_var.set("Stop All" if any_active else "Start All")
        _apply_button_state(self.visualizer_global_autoplay_btn, global_enabled)
        _apply_button_state(self.visualizer_fullscreen_global_autoplay_btn, global_enabled)

        if any_active and global_enabled:
            self._start_visualizer_autoplay_timer()
        else:
            self._stop_visualizer_autoplay_timer()
            self.visualizer_autoplay_current_key = None
            self.visualizer_autoplay_cycle_start_index = None
            self.visualizer_autoplay_cycle_steps = 0

    def _toggle_visualizer_autoplay(self, key: str):
        if key not in self.visualizer_autoplay_active:
            return
        active = bool(self.visualizer_autoplay_active.get(key))
        if active:
            self.visualizer_autoplay_active[key] = False
            if self.visualizer_autoplay_current_key == key:
                self.visualizer_autoplay_last_key = key
                self.visualizer_autoplay_current_key = None
                self.visualizer_autoplay_cycle_start_index = None
                self.visualizer_autoplay_cycle_steps = 0
        else:
            if self._visualizer_autoplay_range(key) <= 1:
                return
            self.visualizer_autoplay_active[key] = True
            self.visualizer_autoplay_current_key = None
            self.visualizer_autoplay_cycle_start_index = None
            self.visualizer_autoplay_cycle_steps = 0
        self._update_visualizer_autoplay_controls()

    def _toggle_visualizer_autoplay_all(self):
        any_active = any(self.visualizer_autoplay_active.values())
        if any_active:
            for key in self.visualizer_autoplay_active:
                self.visualizer_autoplay_active[key] = False
            self.visualizer_autoplay_current_key = None
            self.visualizer_autoplay_cycle_start_index = None
            self.visualizer_autoplay_cycle_steps = 0
            self._update_visualizer_autoplay_controls()
            return

        run_cfg = self.last_run_payload.get("run_config") if isinstance(self.last_run_payload, dict) else None
        available = set(self._visualizer_available_autoplay_keys(run_cfg if isinstance(run_cfg, dict) else None))
        for key in self.visualizer_autoplay_active:
            self.visualizer_autoplay_active[key] = key in available and self._visualizer_autoplay_range(key) > 1
        self.visualizer_autoplay_current_key = None
        self.visualizer_autoplay_cycle_start_index = None
        self.visualizer_autoplay_cycle_steps = 0
        self.visualizer_autoplay_last_key = None
        self._update_visualizer_autoplay_controls()

    def _visualizer_mapping_variants(self, run_config: dict, selected_family: str) -> list[str]:
        tab_id = str(run_config.get("tab_id") or "").strip().lower()
        if tab_id == "subgraph":
            baseline = "vf3_baseline"
            path = self.binary_paths.get(baseline)
            if path is None or not path.exists():
                raise RuntimeError("VF3 baseline binary is required for subgraph visualizer mappings.")
            return [baseline]
        if tab_id == "shortest_path":
            baseline = "dijkstra_baseline" if selected_family == "dijkstra" else "sp_via_baseline"
            path = self.binary_paths.get(baseline)
            if path is None or not path.exists():
                raise RuntimeError(f"{baseline} binary is required for shortest-path visualizer mappings.")
            return [baseline]
        return self._visualizer_variants_for_family(run_config, selected_family)

    def _visualizer_cache_key(
        self,
        run_config: dict,
        *,
        selected_family: str,
        datapoint: dict,
        seeds: list[int],
    ) -> str:
        payload = {
            "tab_id": run_config.get("tab_id"),
            "family": selected_family,
            "k_mode": run_config.get("k_mode"),
            "point": {
                "n": datapoint.get("n"),
                "k": datapoint.get("k"),
                "k_nodes": datapoint.get("k_nodes"),
                "density": datapoint.get("density"),
            },
            "seeds": list(seeds),
            "cap": int(VISUALIZER_SOLUTION_CAP),
        }
        raw = json.dumps(payload, sort_keys=True, default=serialize_for_json)
        return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()

    def _visualizer_iteration_cache_path(self, context: dict, iteration_index: int) -> Path:
        cache_dir = Path(context["cache_dir"])
        return cache_dir / f"iter_{int(iteration_index) + 1:06d}.json"

    def _load_visualizer_iteration_from_disk(self, context: dict, iteration_index: int) -> dict | None:
        path = self._visualizer_iteration_cache_path(context, iteration_index)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _save_visualizer_iteration_to_disk(self, context: dict, iteration_index: int, payload: dict):
        path = self._visualizer_iteration_cache_path(context, iteration_index)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, default=serialize_for_json) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _compute_visualizer_iteration_payload(self, context: dict, iteration_index: int) -> dict:
        run_config = context["run_config"]
        selected_family = str(context["selected_family"])
        visualization_algo = str(context["visualization_algo"])
        datapoint = dict(context["datapoint"])
        seeds = list(context["seeds"])
        label_lookup = dict(context["label_lookup"])
        timeout_seconds = float(context["timeout_seconds"])
        variant_ids = list(context["variant_ids"])
        cache_dir = Path(context["cache_dir"])

        seed = int(seeds[iteration_index])
        iter_dir = cache_dir / "inputs" / f"iter_{iteration_index + 1:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)

        if selected_family in {"dijkstra", "sp_via"}:
            inputs = {
                "dijkstra_file": generate_dijkstra_inputs(
                    iter_dir,
                    int(round(float(datapoint["n"]))),
                    float(datapoint["density"]),
                    int(seed),
                    graph_family=str(run_config.get("graph_family") or "random_density"),
                )
            }
        else:
            inputs = generate_subgraph_inputs(
                iter_dir,
                int(round(float(datapoint["n"]))),
                int(round(float(datapoint["k_nodes"]))),
                float(datapoint["density"]),
                int(seed),
                graph_family=str(run_config.get("graph_family") or "random_density"),
            )

        outputs: dict[str, str] = {}
        for variant_id in variant_ids:
            command = self._build_visualizer_variant_command(variant_id, inputs)
            binary = self.binary_paths.get(variant_id)
            if binary is None:
                outputs[variant_id] = ""
                continue
            try:
                outputs[variant_id] = self._run_visualizer_command(
                    command,
                    cwd=binary.parent,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                outputs[variant_id] = ""
                self._append_log_threadsafe(
                    f"Visualizer capture warning ({variant_id}, iter {iteration_index + 1}): {exc}",
                    level="warn",
                )

        # Fallback rerun for subgraph mappings in VF3 baseline mode.
        if selected_family not in {"dijkstra", "sp_via"} and "vf3_baseline" in outputs:
            parsed_try = normalize_mappings(
                extract_mappings_from_text(outputs.get("vf3_baseline", ""), limit=VISUALIZER_SOLUTION_CAP),
                int(round(float(datapoint.get("k_nodes", 0)))),
                int(round(float(datapoint.get("n", 0)))),
                limit=1,
            )
            if not parsed_try:
                baseline_binary = self.binary_paths.get("vf3_baseline")
                if baseline_binary is not None:
                    try:
                        rerun_command = [
                            str(baseline_binary),
                            "-u",
                            "-s",
                            "-r",
                            "0",
                            "-e",
                            str(inputs["vf_pattern"]),
                            str(inputs["vf_target"]),
                        ]
                        rerun_out = self._run_visualizer_command(
                            rerun_command,
                            cwd=baseline_binary.parent,
                            timeout_seconds=max(60.0, timeout_seconds),
                        )
                        if rerun_out.strip():
                            outputs["vf3_baseline"] = rerun_out
                    except Exception as exc:
                        self._append_log_threadsafe(
                            f"Visualizer fallback VF3 rerun warning (iter {iteration_index + 1}): {exc}",
                            level="warn",
                        )

        if selected_family in {"dijkstra", "sp_via"}:
            iteration_payload = self._build_dijkstra_visualization_iteration(
                inputs=inputs,
                outputs=outputs,
                label_lookup=label_lookup,
                iteration=iteration_index + 1,
                seed=int(seed),
            )
        else:
            iteration_payload = self._build_subgraph_visualization_iteration(
                inputs=inputs,
                outputs=outputs,
                label_lookup=label_lookup,
                iteration=iteration_index + 1,
                seed=int(seed),
                algorithm=visualization_algo,
                family=("vf3" if selected_family not in {"dijkstra", "sp_via"} else selected_family),
            )
        return iteration_payload

    def _ensure_visualizer_iteration_cached(self, context: dict, iteration_index: int) -> dict | None:
        seeds = list(context.get("seeds") or [])
        idx = int(iteration_index)
        if idx < 0 or idx >= len(seeds):
            return None

        with self.visualizer_cache_lock:
            mem_map = context.setdefault("mem_iterations", {})
            cached = mem_map.get(idx)
        if isinstance(cached, dict):
            return cached

        disk_payload = self._load_visualizer_iteration_from_disk(context, idx)
        if isinstance(disk_payload, dict):
            with self.visualizer_cache_lock:
                context.setdefault("mem_iterations", {})[idx] = disk_payload
            return disk_payload

        payload = self._compute_visualizer_iteration_payload(context, idx)
        with self.visualizer_cache_lock:
            context.setdefault("mem_iterations", {})[idx] = payload
        self._save_visualizer_iteration_to_disk(context, idx, payload)
        return payload

    def _prefetch_visualizer_window(self, context: dict, center_index: int):
        seeds = list(context.get("seeds") or [])
        if not seeds:
            return
        low = max(0, int(center_index) - int(VISUALIZER_PREFETCH_RADIUS))
        high = min(len(seeds) - 1, int(center_index) + int(VISUALIZER_PREFETCH_RADIUS))
        for idx in range(low, high + 1):
            try:
                self._ensure_visualizer_iteration_cached(context, idx)
            except Exception:
                continue

    def _start_visualizer_prefetch(self, context_key: str, center_index: int):
        with self.visualizer_cache_lock:
            self.visualizer_prefetch_context_key = str(context_key)
            self.visualizer_prefetch_center_index = int(center_index)
            running = self.visualizer_prefetch_thread is not None and self.visualizer_prefetch_thread.is_alive()
            if running:
                return

        def _worker():
            while True:
                with self.visualizer_cache_lock:
                    request_key = self.visualizer_prefetch_context_key
                    request_center = self.visualizer_prefetch_center_index
                    context = self.visualizer_bundle_cache_mem.get(str(request_key or ""))
                    self.visualizer_prefetch_context_key = None
                    self.visualizer_prefetch_center_index = None
                if not request_key or request_center is None or context is None:
                    break
                self._prefetch_visualizer_window(context, int(request_center))
                with self.visualizer_cache_lock:
                    if self.visualizer_prefetch_context_key is None:
                        break
            with self.visualizer_cache_lock:
                self.visualizer_prefetch_thread = None

        thread = threading.Thread(target=_worker, daemon=True)
        with self.visualizer_cache_lock:
            self.visualizer_prefetch_thread = thread
        thread.start()

    def _shift_visualizer_variable(self, var_id: str, delta: int):
        if self.visualizer_is_loading:
            return
        values = self.visualizer_nav_values.get(var_id, [])
        if len(values) <= 1:
            return
        old = int(self.visualizer_nav_index.get(var_id, 0))
        new = max(0, min(old + int(delta), len(values) - 1))
        if new == old:
            return
        self.visualizer_nav_index[var_id] = new
        run_config = self.last_run_payload.get("run_config") if isinstance(self.last_run_payload, dict) else None
        self._update_visualizer_nav_controls(run_config if isinstance(run_config, dict) else None)
        self._on_visualizer_variable_changed()

    def _on_visualizer_variable_changed(self):
        if not self.visualizer_point_rows:
            return
        payload = self.last_run_payload if isinstance(self.last_run_payload, dict) else None
        run_config = payload.get("run_config") if isinstance(payload, dict) else None
        if not isinstance(run_config, dict):
            return
        selected = self._selected_visualizer_point(run_config)
        if not selected:
            self.visualizer_status_var.set("Selection updated, but no datapoint is available for loading.")
            return
        item = self._find_visualizer_item_for_selected_point(selected)
        if item is None:
            self.visualizer_status_var.set("No datapoint was recorded for this variable combination.")
            self.visualizer_no_solution_var.set("No datapoint was recorded for this variable combination.")
            self.visualizer_active_context_key = None
            self._clear_visualizer_render()
            return
        self.visualizer_no_solution_var.set("")
        self.visualizer_status_var.set("Selection updated. Loading visualizer for selected tuple...")
        self._start_visualizer_job(mode="embed", auto=True)

    def _load_visualizer_in_tab(self):
        self._start_visualizer_job(mode="embed", auto=False)

    def _open_visualizer_external(self):
        self._start_visualizer_job(mode="external", auto=False)

    def _open_visualizer_fullscreen(self):
        self._start_visualizer_job(mode="fullscreen", auto=False)

    def _start_visualizer_job(self, mode: str, auto: bool = False):
        payload = self.last_run_payload
        if not payload or not isinstance(payload, dict):
            if not auto:
                messagebox.showwarning(APP_TITLE, "Run a benchmark first so the visualizer has data.")
            return
        if not self.session_output_dir:
            if not auto:
                messagebox.showwarning(APP_TITLE, "No output directory is available for this run.")
            return
        if self.visualizer_is_loading:
            return
        run_config = payload.get("run_config")
        if not isinstance(run_config, dict):
            if not auto:
                messagebox.showwarning(APP_TITLE, "Run config is unavailable for this benchmark payload.")
            return
        if str(run_config.get("input_mode") or "independent").strip().lower() == "datasets":
            if not auto:
                messagebox.showwarning(APP_TITLE, "Visualizer is currently available for generated-input runs only.")
            return
        selected_point = self._selected_visualizer_point(run_config)
        if not selected_point:
            if not auto:
                messagebox.showwarning(APP_TITLE, "No visualizer datapoint is selected.")
            return
        if self._find_visualizer_item_for_selected_point(selected_point) is None:
            self.visualizer_status_var.set("No datapoint was recorded for this variable combination.")
            self.visualizer_no_solution_var.set("No datapoint was recorded for this variable combination.")
            self.visualizer_active_context_key = None
            self._clear_visualizer_render()
            return
        self.visualizer_is_loading = True
        self._update_visualizer_nav_controls(run_config)
        self.load_visualizer_btn.configure(state=tk.DISABLED)
        self.open_visualizer_btn.configure(state=tk.DISABLED)
        self.visualizer_fullscreen_btn.configure(state=tk.DISABLED)
        point_text = ", ".join(
            f"{self._axis_label(k, run_config)}={self._format_point_value(k, float(v), run_config)}"
            for k, v in selected_point.items()
        )
        self.visualizer_status_var.set(f"Preparing visualizer data for selected tuple ({point_text})...")
        worker = threading.Thread(
            target=self._open_visualizer_worker,
            args=(payload, mode, dict(selected_point)),
            daemon=True,
        )
        worker.start()

    def _prepare_visualizer_native_payload(
        self,
        payload: dict,
        *,
        selected_point: dict[str, float],
    ) -> tuple[str, dict, str]:
        if not self.session_output_dir:
            raise RuntimeError("Session output directory is unavailable.")
        run_config = payload.get("run_config")
        if not isinstance(run_config, dict):
            raise RuntimeError("Run config is missing from benchmark payload.")
        tab_id = str(run_config.get("tab_id") or "").strip().lower()
        if tab_id not in {"subgraph", "shortest_path"}:
            raise RuntimeError(f"Unsupported tab for visualizer: {tab_id}")

        selected_family, view_label, visualization_algo = self._visualizer_family_context(run_config)
        datapoint, seeds, point_idx = self._select_visualizer_datapoint(
            payload,
            selected_family,
            selected_point=selected_point,
        )
        variant_ids = self._visualizer_mapping_variants(run_config, selected_family)
        label_lookup = self._variant_label_lookup(run_config)
        solver_timeout = run_config.get("solver_timeout_seconds")
        timeout_seconds = float(solver_timeout) if isinstance(solver_timeout, (int, float)) and float(solver_timeout) > 0 else 45.0

        cache_key = self._visualizer_cache_key(
            run_config,
            selected_family=selected_family,
            datapoint=datapoint,
            seeds=seeds,
        )
        cache_root = self._visualizer_cache_root()
        if cache_root is None:
            raise RuntimeError("Visualizer cache root is unavailable.")
        cache_dir = cache_root / cache_key
        cache_dir.mkdir(parents=True, exist_ok=True)

        with self.visualizer_cache_lock:
            context = self.visualizer_bundle_cache_mem.get(cache_key)
            if context is None:
                context = {
                    "cache_key": cache_key,
                    "run_config": run_config,
                    "selected_family": selected_family,
                    "view_label": view_label,
                    "visualization_algo": visualization_algo,
                    "datapoint": dict(datapoint),
                    "point_idx": point_idx,
                    "seeds": list(seeds),
                    "variant_ids": list(variant_ids),
                    "label_lookup": dict(label_lookup),
                    "timeout_seconds": float(timeout_seconds),
                    "cache_dir": str(cache_dir),
                    "mem_iterations": {},
                }
                self.visualizer_bundle_cache_mem[cache_key] = context

        seeds_len = len(seeds)
        if seeds_len <= 0:
            raise RuntimeError("No visualization iterations were generated.")
        center_index = max(0, min(int(self.visualizer_iteration_index), seeds_len - 1))
        self._prefetch_visualizer_window(context, center_index)
        self._start_visualizer_prefetch(cache_key, center_index)

        iterations_payloads: list[dict] = []
        mem_map = context.get("mem_iterations", {})
        for idx in range(seeds_len):
            entry = mem_map.get(idx)
            if isinstance(entry, dict):
                iterations_payloads.append(entry)
            else:
                iterations_payloads.append({"_lazy_idx": idx, "iteration": idx + 1})

        first_payload = None
        for entry in iterations_payloads:
            if isinstance(entry, dict) and "_lazy_idx" not in entry:
                first_payload = entry
                break
        if first_payload is None:
            first_payload = self._ensure_visualizer_iteration_cached(context, center_index)
            if not isinstance(first_payload, dict):
                raise RuntimeError("Failed to prepare visualizer iteration payload.")
            iterations_payloads[center_index] = first_payload

        visualization_root = dict(first_payload)
        visualization_root["visualization_iterations"] = iterations_payloads
        visualization_result = {
            "algorithm": visualization_algo,
            "status": "completed",
            "visualization": visualization_root,
        }

        point_text = f"N={int(round(float(datapoint['n'])))} density={float(datapoint['density']):.4f}"
        if selected_family not in {"dijkstra", "sp_via"}:
            point_text += f" k_nodes={int(round(float(datapoint['k_nodes'])))}"
        note = (
            f"Prepared {view_label} visualizer datapoint"
            f" ({point_text}, iterations={len(seeds)}, point_index={point_idx + 1 if point_idx is not None else 'n/a'})."
        )
        return note, visualization_result, cache_key

    def _open_visualizer_worker(self, payload: dict, mode: str, selected_point: dict[str, float]):
        error: Exception | None = None
        html_path: Path | None = None
        status_note = ""
        visualization_result: dict | None = None
        context_key: str | None = None
        try:
            if mode == "external":
                html_path, status_note, visualization_result = self._build_visualizer_bundle(payload, selected_point=selected_point)
                webbrowser.open_new_tab(html_path.resolve().as_uri())
                self._append_log_threadsafe(f"Prepared visualizer: {html_path}", level="notice")
            else:
                status_note, visualization_result, context_key = self._prepare_visualizer_native_payload(
                    payload,
                    selected_point=selected_point,
                )
                self._append_log_threadsafe("Prepared visualizer data from cache/baseline mappings.", level="notice")
        except Exception as exc:
            error = exc
            self._append_log_threadsafe(f"Failed to open visualizer: {exc}", level="error")

        def _finish():
            self.visualizer_is_loading = False
            has_payload = bool(self.last_run_payload)
            run_cfg = self.last_run_payload.get("run_config") if isinstance(self.last_run_payload, dict) else None
            self._update_visualizer_nav_controls(run_cfg if isinstance(run_cfg, dict) else None)
            self.load_visualizer_btn.configure(state=(tk.NORMAL if has_payload and self.visualizer_point_rows else tk.DISABLED))
            self.open_visualizer_btn.configure(state=(tk.NORMAL if has_payload else tk.DISABLED))
            self.visualizer_fullscreen_btn.configure(state=(tk.NORMAL if has_payload and self.visualizer_point_rows else tk.DISABLED))
            if error is not None:
                self.visualizer_status_var.set(f"Visualizer failed: {error}")
                if not mode == "embed":
                    messagebox.showerror(APP_TITLE, f"Failed to open visualizer:\n{error}")
            else:
                if context_key:
                    self.visualizer_active_context_key = str(context_key)
                if mode == "external":
                    self.visualizer_status_var.set(status_note or "Visualizer opened externally.")
                elif mode == "fullscreen":
                    self._render_visualizer_result_in_tab(visualization_result)
                    self._show_visualizer_native_fullscreen()
                    self.visualizer_status_var.set(status_note or "Visualizer loaded in fullscreen.")
                else:
                    self._render_visualizer_result_in_tab(visualization_result)
                    self.visualizer_status_var.set(status_note or "Visualizer loaded in tab.")

        self.after(0, _finish)

    def _current_visualizer_iteration_payload(self) -> dict | None:
        if not self.visualizer_iterations:
            return None
        self.visualizer_iteration_index = max(0, min(int(self.visualizer_iteration_index), len(self.visualizer_iterations) - 1))
        payload = self.visualizer_iterations[self.visualizer_iteration_index]
        if not isinstance(payload, dict):
            return None
        lazy_idx = payload.get("_lazy_idx")
        if isinstance(lazy_idx, int):
            context = None
            with self.visualizer_cache_lock:
                if self.visualizer_active_context_key:
                    context = self.visualizer_bundle_cache_mem.get(self.visualizer_active_context_key)
            if isinstance(context, dict):
                realized = self._ensure_visualizer_iteration_cached(context, int(lazy_idx))
                if isinstance(realized, dict):
                    self.visualizer_iterations[self.visualizer_iteration_index] = realized
                    self._start_visualizer_prefetch(str(context.get("cache_key", "")), int(lazy_idx))
                    return realized
            return None
        return payload

    def _current_visualizer_solutions(self) -> list[dict]:
        iteration_payload = self._current_visualizer_iteration_payload()
        if not iteration_payload:
            return []
        raw = iteration_payload.get("solutions")
        if not isinstance(raw, list):
            return []
        return [entry for entry in raw if isinstance(entry, dict)]

    def _update_visualizer_iteration_solution_controls(self):
        def _set_button_state(btn, enabled: bool):
            if btn is not None:
                btn.configure(state=(tk.NORMAL if enabled else tk.DISABLED))

        def _update_jump_states(button_map: dict[int, ttk.Button | None], index: int, total: int):
            for delta, btn in button_map.items():
                target = int(index) + int(delta)
                _set_button_state(btn, 0 <= target < total)

        iter_buttons = {
            -10: self.visualizer_iter_back10_btn,
            -5: self.visualizer_iter_back5_btn,
            -1: self.visualizer_iter_prev_btn,
            1: self.visualizer_iter_next_btn,
            5: self.visualizer_iter_fwd5_btn,
            10: self.visualizer_iter_fwd10_btn,
        }
        sol_buttons = {
            -10: self.visualizer_sol_back10_btn,
            -5: self.visualizer_sol_back5_btn,
            -1: self.visualizer_sol_prev_btn,
            1: self.visualizer_sol_next_btn,
            5: self.visualizer_sol_fwd5_btn,
            10: self.visualizer_sol_fwd10_btn,
        }

        total_iterations = len(self.visualizer_iterations)
        if total_iterations <= 0:
            self.visualizer_iteration_label_var.set("Iteration --")
            self.visualizer_solution_label_var.set("Solution --")
            self.visualizer_solution_count_var.set("Solution Count: --")
            self.visualizer_no_solution_var.set("")
            _update_jump_states(iter_buttons, 0, 0)
            _update_jump_states(sol_buttons, 0, 0)
            self._sync_visualizer_fullscreen_controls()
            self._update_visualizer_autoplay_controls()
            return

        self.visualizer_iteration_index = max(0, min(int(self.visualizer_iteration_index), total_iterations - 1))
        self.visualizer_iteration_label_var.set(f"Iteration {self.visualizer_iteration_index + 1} of {total_iterations}")
        _update_jump_states(iter_buttons, int(self.visualizer_iteration_index), int(total_iterations))

        solutions = self._current_visualizer_solutions()
        total_solutions = len(solutions)
        if total_solutions <= 0:
            self.visualizer_solution_index = 0
            self.visualizer_solution_label_var.set("Solution 0 of 0")
            self.visualizer_solution_count_var.set("Solution Count: 0")
            self.visualizer_no_solution_var.set("No solutions found for this selection.")
            _update_jump_states(sol_buttons, 0, 0)
            self._sync_visualizer_fullscreen_controls()
            self._update_visualizer_autoplay_controls()
            return

        self.visualizer_solution_index = max(0, min(int(self.visualizer_solution_index), total_solutions - 1))
        current_solution = solutions[self.visualizer_solution_index]
        name = str(current_solution.get("name") or "").strip()
        if name:
            self.visualizer_solution_label_var.set(
                f"Solution {self.visualizer_solution_index + 1} of {total_solutions}: {name}"
            )
        else:
            self.visualizer_solution_label_var.set(f"Solution {self.visualizer_solution_index + 1} of {total_solutions}")

        current_iter = self._current_visualizer_iteration_payload() or {}
        cap_note = " (capped)" if bool(current_iter.get("solution_cap_reached")) else ""
        self.visualizer_solution_count_var.set(f"Solution Count: {total_solutions}{cap_note}")
        self.visualizer_no_solution_var.set("")
        _update_jump_states(sol_buttons, int(self.visualizer_solution_index), int(total_solutions))
        self._sync_visualizer_fullscreen_controls()
        self._update_visualizer_autoplay_controls()

    def _visualizer_shift_iteration(self, delta: int):
        total = len(self.visualizer_iterations)
        if total <= 0:
            return
        old = int(self.visualizer_iteration_index)
        new = max(0, min(old + int(delta), total - 1))
        if new == old:
            return
        self.visualizer_iteration_index = new
        self.visualizer_solution_index = 0
        self._render_visualizer_current_iteration()

    def _visualizer_shift_solution(self, delta: int):
        solutions = self._current_visualizer_solutions()
        total = len(solutions)
        if total <= 0:
            return
        old = int(self.visualizer_solution_index)
        new = max(0, min(old + int(delta), total - 1))
        if new == old:
            return
        self.visualizer_solution_index = new
        self._render_visualizer_current_iteration()

    def _visualizer_prev_iteration(self):
        self._visualizer_shift_iteration(-1)

    def _visualizer_next_iteration(self):
        self._visualizer_shift_iteration(1)

    def _visualizer_prev_solution(self):
        self._visualizer_shift_solution(-1)

    def _visualizer_next_solution(self):
        self._visualizer_shift_solution(1)

    def _visualizer_circle_positions(self, node_ids: list[str]) -> dict[str, tuple[float, float]]:
        n = len(node_ids)
        if n <= 0:
            return {}
        if n == 1:
            return {node_ids[0]: (0.0, 0.0)}
        out: dict[str, tuple[float, float]] = {}
        for idx, node_id in enumerate(node_ids):
            angle = (2.0 * math.pi * float(idx)) / float(n)
            out[node_id] = (math.cos(angle), math.sin(angle))
        return out

    def _draw_visualizer_graph_axis(
        self,
        ax,
        *,
        nodes: list[dict],
        edges: list[dict],
        highlight_nodes: list[str],
        highlight_edges: list[str],
        title: str,
        show_labels: bool,
    ):
        node_ids: list[str] = []
        for entry in nodes:
            if not isinstance(entry, dict):
                continue
            data = entry.get("data")
            if not isinstance(data, dict):
                continue
            raw_id = data.get("id")
            if raw_id is None:
                continue
            node_ids.append(str(raw_id))
        if not node_ids:
            ax.set_title(title)
            ax.text(0.5, 0.5, "No nodes available", ha="center", va="center", transform=ax.transAxes, color="#666666")
            ax.set_axis_off()
            return

        def _sort_key(raw: str):
            try:
                return (0, int(raw))
            except Exception:
                return (1, raw)

        node_ids = sorted(set(node_ids), key=_sort_key)
        pos = self._visualizer_circle_positions(node_ids)
        highlight_node_set = {str(v) for v in (highlight_nodes or [])}
        highlight_edge_set = {str(v) for v in (highlight_edges or [])}

        normal_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        highlighted_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for entry in edges:
            if not isinstance(entry, dict):
                continue
            data = entry.get("data")
            if not isinstance(data, dict):
                continue
            src = str(data.get("source", ""))
            dst = str(data.get("target", ""))
            if src not in pos or dst not in pos:
                continue
            edge_id = str(data.get("id") or f"{src}-{dst}")
            segment = (pos[src], pos[dst])
            if edge_id in highlight_edge_set:
                highlighted_segments.append(segment)
            else:
                normal_segments.append(segment)

        if normal_segments:
            ax.add_collection(LineCollection(normal_segments, colors="#d0d7de", linewidths=0.8, zorder=1))
        if highlighted_segments:
            ax.add_collection(LineCollection(highlighted_segments, colors="#e45756", linewidths=2.0, zorder=2))

        normal_xy = [pos[node_id] for node_id in node_ids if node_id not in highlight_node_set]
        highlight_xy = [pos[node_id] for node_id in node_ids if node_id in highlight_node_set]
        if normal_xy:
            xs = [xy[0] for xy in normal_xy]
            ys = [xy[1] for xy in normal_xy]
            ax.scatter(xs, ys, s=26, c="#7aa6c2", edgecolors="none", zorder=3)
        if highlight_xy:
            xs = [xy[0] for xy in highlight_xy]
            ys = [xy[1] for xy in highlight_xy]
            ax.scatter(xs, ys, s=44, c="#e45756", edgecolors="none", zorder=4)

        if show_labels:
            for node_id in node_ids:
                x, y = pos[node_id]
                ax.text(x, y, node_id, fontsize=7, ha="center", va="center", color="#1f2d3d", zorder=5)

        ax.set_title(title)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(-1.15, 1.15)
        ax.set_ylim(-1.15, 1.15)
        ax.set_axis_off()

    def _build_visualizer_native_figure(self, target_fig: Figure | None = None) -> Figure | None:
        current = self._current_visualizer_iteration_payload()
        if not current:
            if target_fig is not None:
                try:
                    target_fig.clear()
                except Exception:
                    pass
            return None
        solutions = self._current_visualizer_solutions()
        if solutions:
            self.visualizer_solution_index = max(0, min(int(self.visualizer_solution_index), len(solutions) - 1))
            selected_solution = solutions[self.visualizer_solution_index]
        else:
            self.visualizer_solution_index = 0
            selected_solution = None

        nodes = current.get("nodes") if isinstance(current.get("nodes"), list) else []
        edges = current.get("edges") if isinstance(current.get("edges"), list) else []
        highlight_nodes = []
        highlight_edges = []
        pattern_mapping = []
        if isinstance(selected_solution, dict):
            highlight_nodes = list(selected_solution.get("highlight_nodes") or [])
            highlight_edges = list(selected_solution.get("highlight_edges") or [])
            pattern_mapping = list(selected_solution.get("mapping") or [])
        else:
            highlight_nodes = list(current.get("highlight_nodes") or [])
            highlight_edges = list(current.get("highlight_edges") or [])
            pattern_mapping = list(current.get("pattern_nodes") or [])

        pattern_count = int(current.get("pattern_node_count") or 0)
        pattern_edges_raw = current.get("pattern_edges") if isinstance(current.get("pattern_edges"), list) else []
        has_pattern = pattern_count > 0 and len(pattern_edges_raw) > 0

        fig = target_fig if target_fig is not None else Figure(figsize=(11.0, 6.2), dpi=100)
        try:
            fig.clear()
        except Exception:
            pass
        try:
            fig.set_size_inches(11.0, 6.2, forward=False)
            fig.set_dpi(100)
        except Exception:
            pass
        if has_pattern:
            ax_pattern = fig.add_subplot(1, 2, 1)
            ax_graph = fig.add_subplot(1, 2, 2)
        else:
            ax_pattern = None
            ax_graph = fig.add_subplot(1, 1, 1)

        node_count = int(current.get("node_count") or len(nodes))
        edge_count = int(current.get("edge_count") or len(edges))
        truncated = bool(current.get("truncated"))
        graph_title = f"Target Graph (nodes={node_count}, edges={edge_count})"
        if truncated:
            graph_title += " [truncated]"
        show_target_labels = node_count <= 80
        self._draw_visualizer_graph_axis(
            ax_graph,
            nodes=nodes,
            edges=edges,
            highlight_nodes=[str(v) for v in highlight_nodes],
            highlight_edges=[str(v) for v in highlight_edges],
            title=graph_title,
            show_labels=show_target_labels,
        )

        if ax_pattern is not None:
            pattern_nodes = [{"data": {"id": str(idx)}} for idx in range(pattern_count)]
            pattern_edges: list[dict] = []
            for edge in pattern_edges_raw:
                if not isinstance(edge, list) or len(edge) < 2:
                    continue
                try:
                    src = int(edge[0])
                    dst = int(edge[1])
                except Exception:
                    continue
                pattern_edges.append({"data": {"id": f"{src}-{dst}", "source": str(src), "target": str(dst)}})
            self._draw_visualizer_graph_axis(
                ax_pattern,
                nodes=pattern_nodes,
                edges=pattern_edges,
                highlight_nodes=[],
                highlight_edges=[],
                title=f"Pattern Graph (nodes={pattern_count}, edges={len(pattern_edges)})",
                show_labels=pattern_count <= 120,
            )
            if pattern_mapping:
                label_limit = min(pattern_count, len(pattern_mapping))
                positions = self._visualizer_circle_positions([str(i) for i in range(pattern_count)])
                for idx in range(label_limit):
                    mapped = pattern_mapping[idx]
                    if mapped is None:
                        continue
                    xy = positions.get(str(idx))
                    if xy is None:
                        continue
                    ax_pattern.text(
                        xy[0],
                        xy[1] - 0.085,
                        f"-> {mapped}",
                        fontsize=6,
                        ha="center",
                        va="top",
                        color="#0B5CAD",
                        zorder=6,
                    )

        iteration_num = int(current.get("iteration") or (self.visualizer_iteration_index + 1))
        seed_val = current.get("seed")
        title = f"Iteration {iteration_num} | Seed {seed_val}"
        if str(current.get("algorithm") or "").strip().lower() == "dijkstra":
            start_node = current.get("start_node", current.get("start_label"))
            end_node = current.get("end_node", current.get("target_label"))
            path_len = current.get("shortest_path_length")
            meta_parts: list[str] = []
            if start_node is not None and str(start_node).strip() != "":
                meta_parts.append(f"Start: {start_node}")
            if end_node is not None and str(end_node).strip() != "":
                meta_parts.append(f"End: {end_node}")
            if isinstance(path_len, (int, float)):
                meta_parts.append(f"Path Length: {int(path_len)}")
            if meta_parts:
                title += "\n" + " | ".join(meta_parts)
        fig.suptitle(title, fontsize=11)
        if not solutions:
            fig.text(0.5, 0.02, "No solutions found for this iteration.", ha="center", va="bottom", color="#B00020")
        fig.tight_layout(rect=(0.0, 0.04, 1.0, 0.95))
        return fig

    def _render_visualizer_current_iteration(self):
        self._update_visualizer_iteration_solution_controls()
        if self.visualizer_active_context_key:
            self._start_visualizer_prefetch(self.visualizer_active_context_key, int(self.visualizer_iteration_index))
        if self.visualizer_graph_canvas is None:
            fig = self._build_visualizer_native_figure(None)
        else:
            fig = self._build_visualizer_native_figure(self.visualizer_graph_fig)
        if fig is None:
            self._clear_visualizer_render()
            return
        self.visualizer_graph_fig = fig
        if self.visualizer_graph_canvas is None:
            self.visualizer_graph_canvas = FigureCanvasTkAgg(fig, master=self.visualizer_host_frame)
            self.visualizer_graph_canvas.draw()
            self.visualizer_graph_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        else:
            try:
                self.visualizer_graph_canvas.draw()
            except Exception:
                # Fallback to full widget recreation only if redraw fails.
                self.visualizer_graph_canvas = self._render_figure_in_frame(
                    self.visualizer_host_frame,
                    fig,
                    self.visualizer_graph_canvas,
                )
        self._refresh_visualizer_host_scrollregion()
        self._refresh_visualizer_fullscreen_canvas()

    def _render_visualizer_result_in_tab(self, visualization_result: dict | None):
        if not isinstance(visualization_result, dict):
            self._clear_visualizer_render()
            self._refresh_visualizer_fullscreen_canvas()
            return
        vis_root = visualization_result.get("visualization")
        if not isinstance(vis_root, dict):
            self._clear_visualizer_render()
            self.visualizer_no_solution_var.set("No visualization payload was generated.")
            self._refresh_visualizer_fullscreen_canvas()
            return
        iterations_raw = vis_root.get("visualization_iterations")
        if isinstance(iterations_raw, list) and iterations_raw:
            iterations = [entry for entry in iterations_raw if isinstance(entry, dict)]
        else:
            iterations = [vis_root] if isinstance(vis_root, dict) else []
        if not iterations:
            self._clear_visualizer_render()
            self.visualizer_no_solution_var.set("No visualization iterations were generated.")
            self._refresh_visualizer_fullscreen_canvas()
            return
        self.visualizer_loaded_result = visualization_result
        self.visualizer_iterations = iterations
        self.visualizer_iteration_index = 0
        self.visualizer_solution_index = 0
        self._render_visualizer_current_iteration()

    def _close_visualizer_fullscreen_popup(self, _evt=None):
        self._deactivate_visualizer_autoplay()
        popup = self.visualizer_fullscreen_popup
        self.visualizer_fullscreen_popup = None
        if self.visualizer_fullscreen_canvas is not None:
            try:
                self.visualizer_fullscreen_canvas.get_tk_widget().destroy()
            except Exception:
                pass
            self.visualizer_fullscreen_canvas = None
        if self.visualizer_fullscreen_fig is not None:
            try:
                self.visualizer_fullscreen_fig.clear()
            except Exception:
                pass
        self.visualizer_fullscreen_fig = None
        self.visualizer_fullscreen_host = None
        self.visualizer_fullscreen_scroll_canvas = None
        self.visualizer_fullscreen_scroll_xbar = None
        self.visualizer_fullscreen_scroll_ybar = None
        self.visualizer_fullscreen_scroll_window = None
        self.visualizer_fullscreen_nav_rows = {}
        self.visualizer_fullscreen_nav_name_labels = {}
        self.visualizer_fullscreen_nav_prev_buttons = {}
        self.visualizer_fullscreen_nav_next_buttons = {}
        self.visualizer_fullscreen_nav_jump_buttons = {}
        self.visualizer_fullscreen_nav_play_buttons = {}
        self.visualizer_fullscreen_iter_play_btn = None
        self.visualizer_fullscreen_sol_play_btn = None
        self.visualizer_fullscreen_global_autoplay_btn = None
        self.visualizer_fullscreen_iter_back10_btn = None
        self.visualizer_fullscreen_iter_back5_btn = None
        self.visualizer_fullscreen_iter_prev_btn = None
        self.visualizer_fullscreen_iter_next_btn = None
        self.visualizer_fullscreen_iter_fwd5_btn = None
        self.visualizer_fullscreen_iter_fwd10_btn = None
        self.visualizer_fullscreen_sol_back10_btn = None
        self.visualizer_fullscreen_sol_back5_btn = None
        self.visualizer_fullscreen_sol_prev_btn = None
        self.visualizer_fullscreen_sol_next_btn = None
        self.visualizer_fullscreen_sol_fwd5_btn = None
        self.visualizer_fullscreen_sol_fwd10_btn = None
        if popup is not None:
            try:
                popup.destroy()
            except Exception:
                pass

    def _sync_visualizer_fullscreen_controls(self, run_config: dict | None = None):
        popup = self.visualizer_fullscreen_popup
        if popup is None:
            return
        try:
            if not popup.winfo_exists():
                self._close_visualizer_fullscreen_popup()
                return
        except Exception:
            self._close_visualizer_fullscreen_popup()
            return

        if run_config is None and isinstance(self.last_run_payload, dict):
            raw_cfg = self.last_run_payload.get("run_config")
            run_config = raw_cfg if isinstance(raw_cfg, dict) else None

        vars_for_tab = self._visualizer_vars_for_tab(run_config) if isinstance(run_config, dict) else []
        for var_id in ("n", "k", "density"):
            row = self.visualizer_fullscreen_nav_rows.get(var_id)
            if row is None:
                continue
            if var_id in vars_for_tab:
                if not row.winfo_manager():
                    row.pack(fill=tk.X, pady=(1, 1))
            else:
                if row.winfo_manager():
                    row.pack_forget()
                continue
            name_label = self.visualizer_fullscreen_nav_name_labels.get(var_id)
            if name_label is not None and isinstance(run_config, dict):
                try:
                    name_label.configure(text=f"{self._axis_label(var_id, run_config)}:")
                except Exception:
                    pass
            source_prev = self.visualizer_nav_prev_buttons.get(var_id)
            source_next = self.visualizer_nav_next_buttons.get(var_id)
            state_prev = str(source_prev.cget("state")) if source_prev is not None else tk.DISABLED
            state_next = str(source_next.cget("state")) if source_next is not None else tk.DISABLED
            target_prev = self.visualizer_fullscreen_nav_prev_buttons.get(var_id)
            target_next = self.visualizer_fullscreen_nav_next_buttons.get(var_id)
            if target_prev is not None:
                target_prev.configure(state=state_prev)
            if target_next is not None:
                target_next.configure(state=state_next)
            src_jump = self.visualizer_nav_jump_buttons.get(var_id, {})
            dst_jump = self.visualizer_fullscreen_nav_jump_buttons.get(var_id, {})
            for delta, dst_btn in dst_jump.items():
                src_btn = src_jump.get(delta)
                state = str(src_btn.cget("state")) if src_btn is not None else tk.DISABLED
                dst_btn.configure(state=state)

        iter_pairs = [
            (self.visualizer_fullscreen_iter_back10_btn, self.visualizer_iter_back10_btn),
            (self.visualizer_fullscreen_iter_back5_btn, self.visualizer_iter_back5_btn),
            (self.visualizer_fullscreen_iter_prev_btn, self.visualizer_iter_prev_btn),
            (self.visualizer_fullscreen_iter_next_btn, self.visualizer_iter_next_btn),
            (self.visualizer_fullscreen_iter_fwd5_btn, self.visualizer_iter_fwd5_btn),
            (self.visualizer_fullscreen_iter_fwd10_btn, self.visualizer_iter_fwd10_btn),
        ]
        for dst, src in iter_pairs:
            if dst is not None:
                state = str(src.cget("state")) if src is not None else tk.DISABLED
                dst.configure(state=state)

        sol_pairs = [
            (self.visualizer_fullscreen_sol_back10_btn, self.visualizer_sol_back10_btn),
            (self.visualizer_fullscreen_sol_back5_btn, self.visualizer_sol_back5_btn),
            (self.visualizer_fullscreen_sol_prev_btn, self.visualizer_sol_prev_btn),
            (self.visualizer_fullscreen_sol_next_btn, self.visualizer_sol_next_btn),
            (self.visualizer_fullscreen_sol_fwd5_btn, self.visualizer_sol_fwd5_btn),
            (self.visualizer_fullscreen_sol_fwd10_btn, self.visualizer_sol_fwd10_btn),
        ]
        for dst, src in sol_pairs:
            if dst is not None:
                state = str(src.cget("state")) if src is not None else tk.DISABLED
                dst.configure(state=state)

    def _refresh_visualizer_fullscreen_canvas(self):
        popup = self.visualizer_fullscreen_popup
        host = self.visualizer_fullscreen_host
        if popup is None or host is None:
            return
        try:
            if not popup.winfo_exists():
                self._close_visualizer_fullscreen_popup()
                return
        except Exception:
            self._close_visualizer_fullscreen_popup()
            return

        target_fig = self.visualizer_fullscreen_fig if self.visualizer_fullscreen_fig is not None else Figure(figsize=(11.0, 6.2), dpi=100)
        fig = self._build_visualizer_native_figure(target_fig)
        if fig is None:
            fig = target_fig
            try:
                fig.clear()
            except Exception:
                pass
            ax = fig.add_subplot(1, 1, 1)
            ax.text(0.5, 0.5, "No visualizer data loaded.", ha="center", va="center", transform=ax.transAxes, color="#666666")
            ax.set_axis_off()
            fig.tight_layout()

        self.visualizer_fullscreen_fig = fig
        if self.visualizer_fullscreen_canvas is None:
            canvas = FigureCanvasTkAgg(fig, master=host)
            canvas.draw()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            self.visualizer_fullscreen_canvas = canvas
        else:
            try:
                self.visualizer_fullscreen_canvas.draw()
            except Exception:
                try:
                    self.visualizer_fullscreen_canvas.get_tk_widget().destroy()
                except Exception:
                    pass
                canvas = FigureCanvasTkAgg(fig, master=host)
                canvas.draw()
                canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
                self.visualizer_fullscreen_canvas = canvas
        self._refresh_visualizer_fullscreen_scrollregion()
        self._sync_visualizer_fullscreen_controls()

    def _show_visualizer_native_fullscreen(self):
        fig = self._build_visualizer_native_figure()
        if fig is None:
            messagebox.showwarning(APP_TITLE, "No in-tab visualizer is available yet.")
            return
        popup = self.visualizer_fullscreen_popup
        if popup is not None:
            try:
                if popup.winfo_exists():
                    popup.deiconify()
                    popup.lift()
                    popup.focus_force()
                    self._refresh_visualizer_fullscreen_canvas()
                    return
            except Exception:
                self._close_visualizer_fullscreen_popup()

        popup = tk.Toplevel(self)
        popup.title("Visualizer Fullscreen")
        popup.transient(self)
        popup.configure(background="#111111")
        popup.bind("<Escape>", self._close_visualizer_fullscreen_popup)
        popup.protocol("WM_DELETE_WINDOW", self._close_visualizer_fullscreen_popup)
        try:
            popup.attributes("-fullscreen", True)
        except Exception:
            try:
                popup.state("zoomed")
            except Exception:
                pass

        page_wrap = ttk.Frame(popup)
        page_wrap.pack(fill=tk.BOTH, expand=True)
        page_canvas = tk.Canvas(page_wrap, highlightthickness=0, borderwidth=0)
        page_scroll_y = ttk.Scrollbar(page_wrap, orient=tk.VERTICAL, command=page_canvas.yview)
        page_canvas.configure(yscrollcommand=page_scroll_y.set)
        page_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        page_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        page_frame = ttk.Frame(page_canvas)
        self.visualizer_fullscreen_scroll_window = page_canvas.create_window((0, 0), window=page_frame, anchor="nw")
        self.visualizer_fullscreen_scroll_canvas = page_canvas
        self.visualizer_fullscreen_scroll_xbar = None
        self.visualizer_fullscreen_scroll_ybar = page_scroll_y
        page_frame.bind("<Configure>", self._refresh_visualizer_fullscreen_scrollregion)

        def _on_fullscreen_page_canvas_configure(evt):
            if self.visualizer_fullscreen_scroll_canvas is None:
                return
            if self.visualizer_fullscreen_scroll_window is None:
                return
            try:
                self.visualizer_fullscreen_scroll_canvas.itemconfigure(
                    self.visualizer_fullscreen_scroll_window,
                    width=max(1, int(evt.width)),
                )
            except Exception:
                pass
            self._refresh_visualizer_fullscreen_scrollregion()

        page_canvas.bind("<Configure>", _on_fullscreen_page_canvas_configure)

        def _on_fullscreen_mousewheel(evt):
            canvas = self.visualizer_fullscreen_scroll_canvas
            if canvas is None:
                return
            delta = int(getattr(evt, "delta", 0))
            if delta:
                canvas.yview_scroll(int(-delta / 120), "units")

        popup.bind("<MouseWheel>", _on_fullscreen_mousewheel)
        popup.bind("<Button-4>", lambda _evt: self.visualizer_fullscreen_scroll_canvas and self.visualizer_fullscreen_scroll_canvas.yview_scroll(-1, "units"))
        popup.bind("<Button-5>", lambda _evt: self.visualizer_fullscreen_scroll_canvas and self.visualizer_fullscreen_scroll_canvas.yview_scroll(1, "units"))

        top_bar = ttk.Frame(page_frame)
        top_bar.pack(fill=tk.X)
        ttk.Label(top_bar, text="Press Esc to exit fullscreen visualizer").pack(side=tk.LEFT, padx=8, pady=6)
        ttk.Button(top_bar, text="Close", command=self._close_visualizer_fullscreen_popup).pack(side=tk.RIGHT, padx=8, pady=4)

        controls = ttk.Frame(page_frame, padding=(10, 6, 10, 4))
        controls.pack(fill=tk.X)
        ttk.Label(controls, text="Datapoint Selection:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        for var_id in ("n", "k", "density"):
            row = ttk.Frame(controls)
            row.pack(fill=tk.X, pady=(1, 1))
            name_lbl = ttk.Label(row, text=f"{self._axis_label(var_id)}:", width=12)
            name_lbl.pack(side=tk.LEFT)
            back10_btn = ttk.Button(row, text="<<<", width=4, command=lambda v=var_id: self._shift_visualizer_variable(v, -10))
            back10_btn.pack(side=tk.LEFT)
            back5_btn = ttk.Button(row, text="<<", width=4, command=lambda v=var_id: self._shift_visualizer_variable(v, -5))
            back5_btn.pack(side=tk.LEFT, padx=(2, 0))
            prev_btn = ttk.Button(row, text="<", width=3, command=lambda v=var_id: self._shift_visualizer_variable(v, -1))
            prev_btn.pack(side=tk.LEFT, padx=(2, 0))
            value_lbl = tk.Label(
                row,
                textvariable=self.visualizer_nav_display_vars[var_id],
                width=16,
                anchor="center",
                fg="#222222",
            )
            value_lbl.pack(side=tk.LEFT, padx=(6, 6))
            next_btn = ttk.Button(row, text=">", width=3, command=lambda v=var_id: self._shift_visualizer_variable(v, 1))
            next_btn.pack(side=tk.LEFT)
            fwd5_btn = ttk.Button(row, text=">>", width=4, command=lambda v=var_id: self._shift_visualizer_variable(v, 5))
            fwd5_btn.pack(side=tk.LEFT, padx=(2, 0))
            fwd10_btn = ttk.Button(row, text=">>>", width=4, command=lambda v=var_id: self._shift_visualizer_variable(v, 10))
            fwd10_btn.pack(side=tk.LEFT, padx=(2, 0))
            ttk.Label(row, textvariable=self.visualizer_nav_count_vars[var_id], foreground="#666666").pack(side=tk.LEFT, padx=(8, 0))
            auto_key = f"var_{var_id}"
            play_btn = ttk.Button(
                row,
                textvariable=self.visualizer_autoplay_label_vars[auto_key],
                width=6,
                command=lambda k=auto_key: self._toggle_visualizer_autoplay(k),
                state=tk.DISABLED,
            )
            play_btn.pack(side=tk.LEFT, padx=(8, 0))
            self.visualizer_fullscreen_nav_rows[var_id] = row
            self.visualizer_fullscreen_nav_name_labels[var_id] = name_lbl
            self.visualizer_fullscreen_nav_prev_buttons[var_id] = prev_btn
            self.visualizer_fullscreen_nav_next_buttons[var_id] = next_btn
            self.visualizer_fullscreen_nav_play_buttons[var_id] = play_btn
            self.visualizer_fullscreen_nav_jump_buttons[var_id] = {
                -10: back10_btn,
                -5: back5_btn,
                -1: prev_btn,
                1: next_btn,
                5: fwd5_btn,
                10: fwd10_btn,
            }

        iter_sol = ttk.Frame(controls)
        iter_sol.pack(fill=tk.X, pady=(5, 3))
        ttk.Label(iter_sol, text="Iteration:", width=10).pack(side=tk.LEFT)
        self.visualizer_fullscreen_iter_back10_btn = ttk.Button(iter_sol, text="<<<", width=4, command=lambda: self._visualizer_shift_iteration(-10))
        self.visualizer_fullscreen_iter_back10_btn.pack(side=tk.LEFT)
        self.visualizer_fullscreen_iter_back5_btn = ttk.Button(iter_sol, text="<<", width=4, command=lambda: self._visualizer_shift_iteration(-5))
        self.visualizer_fullscreen_iter_back5_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_fullscreen_iter_prev_btn = ttk.Button(iter_sol, text="<", width=3, command=lambda: self._visualizer_shift_iteration(-1))
        self.visualizer_fullscreen_iter_prev_btn.pack(side=tk.LEFT)
        ttk.Label(iter_sol, textvariable=self.visualizer_iteration_label_var, width=20).pack(side=tk.LEFT, padx=(6, 6))
        self.visualizer_fullscreen_iter_next_btn = ttk.Button(iter_sol, text=">", width=3, command=lambda: self._visualizer_shift_iteration(1))
        self.visualizer_fullscreen_iter_next_btn.pack(side=tk.LEFT)
        self.visualizer_fullscreen_iter_fwd5_btn = ttk.Button(iter_sol, text=">>", width=4, command=lambda: self._visualizer_shift_iteration(5))
        self.visualizer_fullscreen_iter_fwd5_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_fullscreen_iter_fwd10_btn = ttk.Button(iter_sol, text=">>>", width=4, command=lambda: self._visualizer_shift_iteration(10))
        self.visualizer_fullscreen_iter_fwd10_btn.pack(side=tk.LEFT, padx=(2, 12))
        ttk.Label(iter_sol, text="Solution:", width=10).pack(side=tk.LEFT)
        self.visualizer_fullscreen_sol_back10_btn = ttk.Button(iter_sol, text="<<<", width=4, command=lambda: self._visualizer_shift_solution(-10))
        self.visualizer_fullscreen_sol_back10_btn.pack(side=tk.LEFT)
        self.visualizer_fullscreen_sol_back5_btn = ttk.Button(iter_sol, text="<<", width=4, command=lambda: self._visualizer_shift_solution(-5))
        self.visualizer_fullscreen_sol_back5_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_fullscreen_sol_prev_btn = ttk.Button(iter_sol, text="<", width=3, command=lambda: self._visualizer_shift_solution(-1))
        self.visualizer_fullscreen_sol_prev_btn.pack(side=tk.LEFT)
        ttk.Label(iter_sol, textvariable=self.visualizer_solution_label_var, width=32).pack(side=tk.LEFT, padx=(6, 6))
        self.visualizer_fullscreen_sol_next_btn = ttk.Button(iter_sol, text=">", width=3, command=lambda: self._visualizer_shift_solution(1))
        self.visualizer_fullscreen_sol_next_btn.pack(side=tk.LEFT)
        self.visualizer_fullscreen_sol_fwd5_btn = ttk.Button(iter_sol, text=">>", width=4, command=lambda: self._visualizer_shift_solution(5))
        self.visualizer_fullscreen_sol_fwd5_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_fullscreen_sol_fwd10_btn = ttk.Button(iter_sol, text=">>>", width=4, command=lambda: self._visualizer_shift_solution(10))
        self.visualizer_fullscreen_sol_fwd10_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.visualizer_fullscreen_iter_play_btn = ttk.Button(
            iter_sol,
            textvariable=self.visualizer_autoplay_label_vars["iteration"],
            width=6,
            command=lambda: self._toggle_visualizer_autoplay("iteration"),
            state=tk.DISABLED,
        )
        self.visualizer_fullscreen_iter_play_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.visualizer_fullscreen_sol_play_btn = ttk.Button(
            iter_sol,
            textvariable=self.visualizer_autoplay_label_vars["solution"],
            width=6,
            command=lambda: self._toggle_visualizer_autoplay("solution"),
            state=tk.DISABLED,
        )
        self.visualizer_fullscreen_sol_play_btn.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(controls, textvariable=self.visualizer_solution_count_var, foreground="#555555").pack(anchor="w", pady=(0, 1))
        ttk.Label(controls, textvariable=self.visualizer_no_solution_var, foreground="#B00020").pack(anchor="w")
        self.visualizer_fullscreen_global_autoplay_btn = ttk.Button(
            controls,
            textvariable=self.visualizer_autoplay_global_label_var,
            command=self._toggle_visualizer_autoplay_all,
            state=tk.DISABLED,
        )
        self.visualizer_fullscreen_global_autoplay_btn.pack(anchor="w", pady=(4, 2))

        host = ttk.Frame(page_frame)
        host.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.visualizer_fullscreen_popup = popup
        self.visualizer_fullscreen_host = host
        self.visualizer_fullscreen_fig = fig
        self.visualizer_fullscreen_canvas = None
        self._refresh_visualizer_fullscreen_canvas()
        self._refresh_visualizer_fullscreen_scrollregion()
        self._update_visualizer_autoplay_controls()

    def _build_visualizer_bundle(
        self,
        payload: dict,
        *,
        selected_point: dict[str, float] | None = None,
    ) -> tuple[Path, str, dict]:
        if not self.session_output_dir:
            raise RuntimeError("Session output directory is unavailable.")
        run_config = payload.get("run_config")
        if not isinstance(run_config, dict):
            raise RuntimeError("Run config is missing from benchmark payload.")
        tab_id = str(run_config.get("tab_id") or "").strip().lower()
        if tab_id not in {"subgraph", "shortest_path"}:
            raise RuntimeError(f"Unsupported tab for visualizer: {tab_id}")
        selected_family, view_label, visualization_algo = self._visualizer_family_context(run_config)
        datapoint, seeds, point_idx = self._select_visualizer_datapoint(
            payload,
            selected_family,
            selected_point=selected_point,
        )
        variant_ids = self._visualizer_mapping_variants(run_config, selected_family)
        if not variant_ids:
            raise RuntimeError(f"No variants available for family '{selected_family}'.")

        label_lookup = self._variant_label_lookup(run_config)
        solver_timeout = run_config.get("solver_timeout_seconds")
        timeout_seconds = float(solver_timeout) if isinstance(solver_timeout, (int, float)) and float(solver_timeout) > 0 else 45.0

        vis_root = self.session_output_dir / "visualizer"
        vis_inputs = vis_root / "inputs"
        if vis_root.exists():
            shutil.rmtree(vis_root, ignore_errors=True)
        vis_inputs.mkdir(parents=True, exist_ok=True)

        iteration_payloads: list[dict] = []
        count_by_variant: dict[str, list[str]] = {vid: [] for vid in variant_ids}

        for iter_idx, seed in enumerate(seeds):
            iter_dir = vis_inputs / f"iter_{iter_idx + 1:03d}"
            iter_dir.mkdir(parents=True, exist_ok=True)

            if selected_family in {"dijkstra", "sp_via"}:
                inputs = {
                    "dijkstra_file": generate_dijkstra_inputs(
                        iter_dir,
                        int(round(float(datapoint["n"]))),
                        float(datapoint["density"]),
                        int(seed),
                        graph_family=str(run_config.get("graph_family") or "random_density"),
                    )
                }
            else:
                inputs = generate_subgraph_inputs(
                    iter_dir,
                    int(round(float(datapoint["n"]))),
                    int(round(float(datapoint["k_nodes"]))),
                    float(datapoint["density"]),
                    int(seed),
                    graph_family=str(run_config.get("graph_family") or "random_density"),
                )

            outputs: dict[str, str] = {}
            for variant_id in variant_ids:
                command = self._build_visualizer_variant_command(variant_id, inputs)
                binary = self.binary_paths.get(variant_id)
                if binary is None:
                    outputs[variant_id] = ""
                    continue
                try:
                    outputs[variant_id] = self._run_visualizer_command(
                        command,
                        cwd=binary.parent,
                        timeout_seconds=timeout_seconds,
                    )
                except Exception as exc:
                    outputs[variant_id] = ""
                    self._append_log_threadsafe(
                        f"Visualizer capture warning ({variant_id}, iter {iter_idx + 1}): {exc}",
                        level="warn",
                    )

                if selected_family in {"dijkstra", "sp_via"}:
                    distance = parse_dijkstra_distance(outputs.get(variant_id, ""))
                    count_by_variant[variant_id].append(distance if distance is not None else "NA")
                else:
                    count = parse_solution_count(outputs.get(variant_id, ""))
                    count_by_variant[variant_id].append(str(count) if count is not None else "NA")

            if selected_family not in {"dijkstra", "sp_via"} and "vf3_baseline" in outputs:
                parsed_try = normalize_mappings(
                    extract_mappings_from_text(outputs.get("vf3_baseline", ""), limit=VISUALIZER_SOLUTION_CAP),
                    int(round(float(datapoint.get("k_nodes", 0)))),
                    int(round(float(datapoint.get("n", 0)))),
                    limit=1,
                )
                if not parsed_try:
                    baseline_binary = self.binary_paths.get("vf3_baseline")
                    if baseline_binary is not None:
                        try:
                            rerun_command = [
                                str(baseline_binary),
                                "-u",
                                "-s",
                                "-r",
                                "0",
                                "-e",
                                str(inputs["vf_pattern"]),
                                str(inputs["vf_target"]),
                            ]
                            rerun_out = self._run_visualizer_command(
                                rerun_command,
                                cwd=baseline_binary.parent,
                                timeout_seconds=max(60.0, timeout_seconds),
                            )
                            if rerun_out.strip():
                                outputs["vf3_baseline"] = rerun_out
                        except Exception as exc:
                            self._append_log_threadsafe(
                                f"Visualizer fallback VF3 rerun warning (iter {iter_idx + 1}): {exc}",
                                level="warn",
                            )

            if selected_family in {"dijkstra", "sp_via"}:
                iteration_payload = self._build_dijkstra_visualization_iteration(
                    inputs=inputs,
                    outputs=outputs,
                    label_lookup=label_lookup,
                    iteration=iter_idx + 1,
                    seed=int(seed),
                )
            else:
                iteration_payload = self._build_subgraph_visualization_iteration(
                    inputs=inputs,
                    outputs=outputs,
                    label_lookup=label_lookup,
                    iteration=iter_idx + 1,
                    seed=int(seed),
                    algorithm=visualization_algo,
                    family=("vf3" if selected_family not in {"dijkstra", "sp_via"} else selected_family),
                )
            iteration_payloads.append(iteration_payload)

        if not iteration_payloads:
            raise RuntimeError("No visualization iterations were generated.")

        visualization_root = dict(iteration_payloads[0])
        visualization_root["visualization_iterations"] = iteration_payloads
        visualization_result = {
            "algorithm": visualization_algo,
            "status": "completed",
            "visualization": visualization_root,
        }
        if selected_family not in {"dijkstra", "sp_via"}:
            lines: list[str] = []
            for variant_id in variant_ids:
                label = label_lookup.get(variant_id, variant_id)
                counts = count_by_variant.get(variant_id, [])
                lines.append(f"[{label}]")
                lines.append(f"Solution counts: [{', '.join(counts)}]")
            visualization_result["output"] = "\n".join(lines)

        js_candidates = [
            resource_root() / "js" / "app" / "07-visualization-api-bootstrap.js",
            adjacent_output_base().parent / "js" / "app" / "07-visualization-api-bootstrap.js",
            Path(__file__).resolve().parent.parent / "js" / "app" / "07-visualization-api-bootstrap.js",
        ]
        js_src = None
        for candidate in js_candidates:
            if candidate.is_file():
                js_src = candidate
                break
        if js_src is None:
            searched = "\n".join(str(path) for path in js_candidates)
            raise RuntimeError(f"Visualizer script not found. Checked:\n{searched}")
        js_dst = vis_root / "07-visualization-api-bootstrap.js"
        shutil.copy2(js_src, js_dst)

        payload_json = json.dumps(visualization_result, default=serialize_for_json)
        html_path = vis_root / "visualizer.html"
        html_path.write_text(
            self._build_visualizer_html(payload_json),
            encoding="utf-8",
        )
        (vis_root / "visualization-payload.json").write_text(
            json.dumps(visualization_result, indent=2, default=serialize_for_json) + "\n",
            encoding="utf-8",
        )

        point_text = f"N={int(round(float(datapoint['n'])))} density={float(datapoint['density']):.4f}"
        if selected_family not in {"dijkstra", "sp_via"}:
            point_text += f" k_nodes={int(round(float(datapoint['k_nodes'])))}"
        note = (
            f"Prepared {view_label} visualizer datapoint"
            f" ({point_text}, iterations={len(seeds)}, point_index={point_idx + 1 if point_idx is not None else 'n/a'})."
        )
        return html_path, note, visualization_result

    def _variant_label_lookup(self, run_config: dict) -> dict[str, str]:
        out: dict[str, str] = {}
        raw = run_config.get("selected_variant_labels")
        if isinstance(raw, dict):
            for key, value in raw.items():
                k = str(key).strip().lower()
                if not k:
                    continue
                out[k] = str(value).strip() or k
        for variant in SOLVER_VARIANTS:
            out.setdefault(variant.variant_id, variant.label)
        return out

    def _visualizer_family_context(self, run_config: dict) -> tuple[str, str, str]:
        tab_id = str(run_config.get("tab_id") or "").strip().lower()
        if tab_id == "shortest_path":
            selected_variants = [str(v).strip().lower() for v in list(run_config.get("selected_variants") or [])]
            if any(v.startswith("sp_via_") for v in selected_variants):
                return "sp_via", "With Intermediate", "sp_via"
            return "dijkstra", "Shortest Path", "dijkstra"
        selected_variants = [str(v).strip().lower() for v in list(run_config.get("selected_variants") or [])]
        # Subgraph view is presented generically; prefer VF3 answers as requested.
        if any(v.startswith("vf3_") for v in selected_variants):
            return "vf3", "Subgraph", "subgraph"
        if any(v.startswith("glasgow_") for v in selected_variants):
            return "glasgow", "Subgraph", "subgraph"
        raise RuntimeError("No subgraph solver family is available for visualizer.")

    def _visualizer_variants_for_family(self, run_config: dict, family: str) -> list[str]:
        prefix = f"{family}_"
        selected = [str(v).strip().lower() for v in list(run_config.get("selected_variants") or [])]
        variants = [v for v in selected if v.startswith(prefix)]
        variants = [v for v in variants if v in self.binary_paths and self.binary_paths[v].exists()]
        if not variants:
            variants = [
                variant.variant_id
                for variant in SOLVER_VARIANTS
                if variant.variant_id.startswith(prefix)
                and variant.variant_id in self.binary_paths
                and self.binary_paths[variant.variant_id].exists()
            ]
        if not variants:
            baseline = f"{family}_baseline"
            if baseline in self.binary_paths and self.binary_paths[baseline].exists():
                variants = [baseline]
        variants.sort(key=lambda vid: (0 if vid.endswith("_baseline") else 1, vid))
        return variants

    def _build_visualizer_variant_command(self, variant_id: str, inputs: dict[str, Path]) -> list[str]:
        binary = self.binary_paths.get(variant_id)
        if binary is None:
            raise RuntimeError(f"Unknown variant: {variant_id}")
        family = variant_family_from_id(variant_id)
        if family in {"dijkstra", "sp_via"}:
            return [str(binary), str(inputs["dijkstra_file"])]
        if family == "vf3":
            if variant_id == "vf3_baseline":
                return [str(binary), "-u", "-s", "-r", "0", "-e", str(inputs["vf_pattern"]), str(inputs["vf_target"])]
            return [str(binary), str(inputs["vf_pattern"]), str(inputs["vf_target"])]
        if family == "glasgow":
            if variant_id == "glasgow_baseline":
                return [
                    str(binary),
                    "--format",
                    "vertexlabelledlad",
                    "--print-all-solutions",
                    "--solution-limit",
                    str(VISUALIZER_SOLUTION_CAP),
                    str(inputs["lad_pattern"]),
                    str(inputs["lad_target"]),
                ]
            return [str(binary), str(inputs["lad_pattern"]), str(inputs["lad_target"])]
        raise RuntimeError(f"Unsupported variant for visualizer: {variant_id}")

    def _run_visualizer_command(self, command: list[str], cwd: Path, timeout_seconds: float) -> str:
        popen_kwargs = {
            "args": command,
            "cwd": str(cwd),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": max(1.0, float(timeout_seconds)),
            "env": runtime_env_for_binary(Path(command[0])),
        }
        if sys.platform.startswith("win"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            popen_kwargs["startupinfo"] = startupinfo
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(**popen_kwargs)
        stdout_text = completed.stdout or ""
        stderr_text = completed.stderr or ""
        combined = (stdout_text + "\n" + stderr_text).strip()
        if completed.returncode != 0:
            raise RuntimeError(
                f"exit code {completed.returncode} for '{subprocess.list2cmdline(command)}'"
                + (f" | {combined[:300]}" if combined else "")
            )
        return combined

    def _visualizer_url(self, html_path: Path) -> str:
        stamp = int(time.time() * 1000)
        return f"{html_path.resolve().as_uri()}?t={stamp}"

    def _launch_pywebview_window(self, html_path: Path, *, fullscreen: bool = False) -> bool:
        if not self.visualizer_popup_webview_enabled:
            return False
        target_url = self._visualizer_url(html_path)
        exe_path = Path(sys.executable).resolve()
        title = APP_TITLE
        if getattr(sys, "frozen", False):
            command = [
                str(exe_path),
                "--visualizer-webview-url",
                target_url,
                "--visualizer-webview-title",
                title,
                "--visualizer-webview-fullscreen",
                "1" if fullscreen else "0",
            ]
        else:
            command = [
                str(exe_path),
                str(Path(__file__).resolve()),
                "--visualizer-webview-url",
                target_url,
                "--visualizer-webview-title",
                title,
                "--visualizer-webview-fullscreen",
                "1" if fullscreen else "0",
            ]
        popen_kwargs = {
            "args": command,
            "cwd": str(Path(__file__).resolve().parent.parent),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform.startswith("win"):
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(**popen_kwargs)
            return True
        except Exception as exc:
            self._append_log_threadsafe(f"Desktop webview launch failed: {exc}", level="warn")
            return False

    def _show_visualizer_in_tab(self, html_path: Path | None):
        if html_path is None:
            return
        if not self.visualizer_embed_enabled or TkWebView2 is None:
            if self._launch_pywebview_window(html_path, fullscreen=False):
                return
            webbrowser.open_new_tab(html_path.resolve().as_uri())
            return
        url = self._visualizer_url(html_path)
        if self.visualizer_webview is None:
            self.visualizer_webview = TkWebView2(self.visualizer_host_frame, width=1000, height=680, url=url)
            self.visualizer_webview.pack(fill=tk.BOTH, expand=True)
        else:
            self.visualizer_webview.load_url(url)

    def _show_visualizer_in_fullscreen(self, html_path: Path | None):
        if html_path is None:
            return
        if not self.visualizer_embed_enabled or TkWebView2 is None:
            if self._launch_pywebview_window(html_path, fullscreen=True):
                return
            webbrowser.open_new_tab(html_path.resolve().as_uri())
            return
        popup = tk.Toplevel(self)
        popup.title("Visualizer Fullscreen")
        popup.transient(self)
        popup.configure(background="#111111")

        def _close_popup(_evt=None):
            popup.destroy()

        popup.bind("<Escape>", _close_popup)
        popup.protocol("WM_DELETE_WINDOW", _close_popup)
        try:
            popup.attributes("-fullscreen", True)
        except Exception:
            try:
                popup.state("zoomed")
            except Exception:
                pass

        top_bar = ttk.Frame(popup)
        top_bar.pack(fill=tk.X)
        ttk.Label(top_bar, text="Press Esc to exit fullscreen visualizer").pack(side=tk.LEFT, padx=8, pady=6)
        ttk.Button(top_bar, text="Close", command=_close_popup).pack(side=tk.RIGHT, padx=8, pady=4)

        host = ttk.Frame(popup)
        host.pack(fill=tk.BOTH, expand=True)
        viewer = TkWebView2(host, width=1400, height=900, url=self._visualizer_url(html_path))
        viewer.pack(fill=tk.BOTH, expand=True)

    def _select_visualizer_datapoint(
        self,
        payload: dict,
        family: str,
        *,
        selected_point: dict[str, float] | None = None,
    ) -> tuple[dict, list[int], int | None]:
        run_config = payload.get("run_config")
        if not isinstance(run_config, dict):
            raise RuntimeError("Run config is missing from payload.")
        datapoints = self._collect_payload_datapoints(payload)
        if not datapoints:
            raise RuntimeError("No datapoints were found in the run payload.")

        baseline_id = f"{family}_baseline"
        family_rows = [row for row in datapoints if str(row.get("variant_id") or "").strip().lower() == baseline_id]
        if not family_rows:
            family_rows = [row for row in datapoints if str(row.get("variant_id") or "").strip().lower().startswith(f"{family}_")]
        if not family_rows:
            raise RuntimeError(f"No datapoints were found for family '{family}'.")

        def _row_sort_key(row: dict):
            x_raw = row.get("x_value")
            y_raw = row.get("y_value")
            x = float(x_raw) if isinstance(x_raw, (int, float)) else float("inf")
            y = float(y_raw) if isinstance(y_raw, (int, float)) else float("-inf")
            return (x, y)

        sorted_rows = sorted(family_rows, key=_row_sort_key)
        row = sorted_rows[0]
        if isinstance(selected_point, dict) and selected_point:
            tol = 1e-9
            for candidate in sorted_rows:
                candidate_point = self._resolve_visualizer_point_from_row(run_config, candidate, family)
                if not candidate_point:
                    continue
                matches = True
                for key, target in selected_point.items():
                    raw = candidate_point.get(key)
                    if not isinstance(raw, (int, float)) or abs(float(raw) - float(target)) > tol:
                        matches = False
                        break
                if matches:
                    row = candidate
                    break

        point = self._resolve_visualizer_point_from_row(run_config, row, family)
        if not point:
            raise RuntimeError("Unable to determine visualization datapoint values from selected run row.")

        iterations = max(1, int(run_config.get("iterations_per_datapoint") or 1))
        point_idx = self._find_datapoint_index_from_run_config(run_config, row)
        seed_raw = run_config.get("seed")
        base_seed = None
        try:
            base_seed = int(seed_raw)
        except Exception:
            base_seed = None

        seeds: list[int] = []
        if point_idx is not None and base_seed is not None:
            seeds = [int(base_seed + (point_idx * 100000) + idx) for idx in range(iterations)]
        if not seeds:
            row_seeds = row.get("seeds")
            if isinstance(row_seeds, list):
                for raw in row_seeds:
                    try:
                        seeds.append(int(raw))
                    except Exception:
                        continue
            if len(seeds) < iterations:
                start_seed = seeds[-1] + 1 if seeds else (base_seed if base_seed is not None else int(time.time()))
                while len(seeds) < iterations:
                    seeds.append(int(start_seed))
                    start_seed += 1
            seeds = seeds[:iterations]

        return point, seeds, point_idx

    def _find_datapoint_index_from_run_config(self, run_config: dict, row: dict) -> int | None:
        stop_mode = str(run_config.get("stop_mode") or "").strip().lower()
        if stop_mode == "timed":
            return None
        primary = str(run_config.get("primary_variable") or "").strip()
        secondary = str(run_config.get("secondary_variable") or "").strip() or None
        if not primary:
            return None
        x_raw = row.get("x_value")
        y_raw = row.get("y_value")
        if not isinstance(x_raw, (int, float)):
            return None
        x_ref = float(x_raw)
        y_ref = float(y_raw) if isinstance(y_raw, (int, float)) else None

        fixed_raw = run_config.get("fixed_values")
        fixed_values = dict(fixed_raw) if isinstance(fixed_raw, dict) else {}
        var_ranges_raw = run_config.get("var_ranges")
        if not isinstance(var_ranges_raw, dict):
            return None
        primary_values = list(var_ranges_raw.get(primary) or [])
        if not primary_values:
            return None
        secondary_values = list(var_ranges_raw.get(secondary) or []) if secondary else [None]
        if secondary and not secondary_values:
            return None

        point_idx = 0
        tol = 1e-9
        for y in secondary_values:
            for x in primary_values:
                point = dict(fixed_values)
                point[primary] = x
                if secondary is not None:
                    point[secondary] = y
                try:
                    x_val = float(point.get(primary))
                except Exception:
                    point_idx += 1
                    continue
                y_val = None
                if secondary is not None:
                    try:
                        y_val = float(point.get(secondary))
                    except Exception:
                        y_val = None
                if abs(x_val - x_ref) <= tol and ((secondary is None) or (y_ref is not None and y_val is not None and abs(y_val - y_ref) <= tol)):
                    return point_idx
                point_idx += 1
        return None

    def _build_visualizer_html(self, payload_json: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Benchmark Visualizer</title>
  <script src="https://cdn.jsdelivr.net/npm/cytoscape@3.29.2/dist/cytoscape.min.js"></script>
  <style>
    body {{
      margin: 0;
      font-family: Segoe UI, Arial, sans-serif;
      background: #f4f7fb;
      color: #1f2d3d;
    }}
    .container {{
      padding: 12px;
      max-width: 1200px;
      margin: 0 auto;
    }}
    .graph-panel {{
      border: 1px solid #d0d7de;
      border-radius: 8px;
      background: #ffffff;
      margin-top: 12px;
      padding: 10px;
    }}
    .graph-panel-small {{
      max-width: 600px;
    }}
    .chart-title {{
      font-weight: 600;
      margin-bottom: 8px;
    }}
    .graph-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }}
    .graph-note {{
      color: #4b5563;
      margin-bottom: 8px;
      font-size: 0.92rem;
    }}
    .graph-canvas {{
      height: 520px;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
    }}
    .graph-canvas-small {{
      height: 280px;
    }}
    .btn {{
      border: 1px solid #cbd5e1;
      background: #f8fafc;
      border-radius: 6px;
      padding: 4px 8px;
      cursor: pointer;
    }}
    .btn:hover {{
      background: #eef2f7;
    }}
    .solution-nav-block {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .solution-controls, .iteration-controls {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .solution-label, .solution-count-display {{
      font-size: 0.9rem;
    }}
    #status-message .error {{
      color: #b00020;
      margin-top: 6px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div id="status-message"></div>
    <div class="graph-panel graph-panel-small" id="pattern-panel" hidden>
      <div class="chart-title">Pattern Visualization</div>
      <div class="graph-actions">
        <button class="btn" id="pattern-center-btn" onclick="centerPatternGraph()" type="button">Center</button>
      </div>
      <div class="graph-note" id="pattern-note"></div>
      <div class="graph-canvas graph-canvas-small" id="pattern-canvas"></div>
    </div>
    <div class="graph-panel" id="graph-panel" hidden>
      <div class="chart-title">Graph Visualization</div>
      <div class="graph-actions">
        <button class="btn" id="graph-center-btn" onclick="centerMainGraph()" type="button">Center</button>
        <div class="iteration-controls" id="iteration-controls">
          <button class="btn" id="iteration-prev-btn" onclick="showPreviousIteration()" type="button">&lt;</button>
          <span class="solution-label" id="iteration-label">Iteration 1</span>
          <button class="btn" id="iteration-next-btn" onclick="showNextIteration()" type="button">&gt;</button>
        </div>
        <div class="solution-nav-block">
          <span class="solution-count-display" id="solution-count-display" hidden>Solution Count: --</span>
          <div class="solution-controls" id="solution-controls">
            <button class="btn" id="solution-prev-btn" onclick="showPreviousSolution()" type="button">&lt;</button>
            <span class="solution-label" id="solution-label">Solution 0</span>
            <button class="btn" id="solution-next-btn" onclick="showNextSolution()" type="button">&gt;</button>
          </div>
          <span class="solution-cap-note" id="solution-cap-note" hidden><em>Visualizer caps at 2000 solutions</em></span>
        </div>
        <span class="solution-warning" id="solution-warning" hidden>No solutions found</span>
      </div>
      <div class="graph-note" id="graph-note"></div>
      <div class="graph-canvas" id="graph-canvas"></div>
    </div>
  </div>
  <script>
    const config = {{}};
    let graphInstance = null;
    let patternInstance = null;
    let graphHoverEdgeId = null;
    let patternHoverEdgeId = null;
    let visSolutions = [];
    let currentSolutionIndex = 0;
    let visIterations = [];
    let currentIterationIndex = 0;
    function updateInputModeVisibility() {{}}
    function updateGeneratorFieldsForAlgorithm() {{}}
    function updateGeneratorEstimate() {{}}
    function updateRunButton() {{}}
    window.__VIS_RESULT__ = {payload_json};
  </script>
  <script src="./07-visualization-api-bootstrap.js"></script>
  <script>
    window.addEventListener('load', () => {{
      try {{
        if (window.__VIS_RESULT__) {{
          renderVisualization(window.__VIS_RESULT__);
        }}
      }} catch (err) {{
        const el = document.getElementById('status-message');
        if (el) {{
          el.innerHTML = `<div class="error">${{String(err)}}</div>`;
        }}
      }}
    }});
  </script>
</body>
</html>
"""

    def _build_subgraph_visualization_iteration(
        self,
        *,
        inputs: dict[str, Path],
        outputs: dict[str, str],
        label_lookup: dict[str, str],
        iteration: int,
        seed: int,
        algorithm: str,
        family: str,
    ) -> dict:
        if family == "vf3":
            pattern_adj = parse_vf_graph(inputs["vf_pattern"])
            target_adj = parse_vf_graph(inputs["vf_target"])
        else:
            pattern_adj = parse_lad_graph(inputs["lad_pattern"])
            target_adj = parse_lad_graph(inputs["lad_target"])

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

        solutions: list[dict] = []
        seen_solution_keys: set[str] = set()
        cap_reached = False
        for variant_id, text in outputs.items():
            parsed = normalize_mappings(
                extract_mappings_from_text(text, limit=VISUALIZER_SOLUTION_CAP),
                pattern_n,
                target_n,
                limit=VISUALIZER_SOLUTION_CAP,
            )
            label = label_lookup.get(variant_id, variant_id)
            for mapping_index, mapping in enumerate(parsed):
                mapping_arr: list[int | None] = [None] * pattern_n
                for p, t in mapping.items():
                    if 0 <= p < pattern_n and 0 <= t < target_n:
                        mapping_arr[p] = t
                key = json.dumps(mapping_arr)
                if key in seen_solution_keys:
                    continue
                seen_solution_keys.add(key)

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
                sol_name = label if mapping_index == 0 else f"{label} #{mapping_index + 1}"
                solutions.append(
                    {
                        "name": sol_name,
                        "mapping": mapping_arr,
                        "highlight_nodes": highlight_nodes,
                        "highlight_edges": highlight_edges,
                    }
                )
                if len(solutions) >= VISUALIZER_SOLUTION_CAP:
                    cap_reached = True
                    break
            if cap_reached:
                break

        first = solutions[0] if solutions else None
        return {
            "algorithm": str(algorithm or "").strip().lower(),
            "seed": int(seed),
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

    def _parse_dijkstra_input_for_visualizer(self, path: Path):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start_label = None
        target_label = None
        if lines and lines[0].lstrip().startswith("#"):
            header = lines[0].strip()
            m_start = re.search(r"start\s*=\s*([^\s#]+)", header, flags=re.IGNORECASE)
            m_target = re.search(r"target\s*=\s*([^\s#]+)", header, flags=re.IGNORECASE)
            if m_start:
                start_label = m_start.group(1).strip()
            if m_target:
                target_label = m_target.group(1).strip()

        csv_text = "\n".join(line for line in lines if not line.lstrip().startswith("#")).strip()
        labels_in_order: list[str] = []
        edges_raw: list[tuple[str, str]] = []
        if csv_text:
            reader = csv.DictReader(csv_text.splitlines())
            for row in reader:
                src = str(row.get("source") or "").strip()
                dst = str(row.get("target") or "").strip()
                if not src or not dst:
                    continue
                edges_raw.append((src, dst))
                labels_in_order.append(src)
                labels_in_order.append(dst)

        unique_labels: list[str] = []
        seen = set()
        for label in labels_in_order:
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            unique_labels.append(label)
        if start_label and start_label.lower() not in seen:
            unique_labels.append(start_label)
            seen.add(start_label.lower())
        if target_label and target_label.lower() not in seen:
            unique_labels.append(target_label)
            seen.add(target_label.lower())

        label_to_id: dict[str, int] = {label: idx for idx, label in enumerate(unique_labels)}
        label_to_id_lower: dict[str, int] = {label.lower(): idx for idx, label in enumerate(unique_labels)}

        all_edges: set[tuple[int, int]] = set()
        for src, dst in edges_raw:
            u = label_to_id.get(src)
            v = label_to_id.get(dst)
            if u is None or v is None:
                continue
            ek = edge_key(u, v)
            if ek is None:
                continue
            all_edges.add(ek)
        return unique_labels, label_to_id, label_to_id_lower, all_edges, start_label, target_label

    def _extract_dijkstra_path_nodes(self, output_text: str, label_to_id: dict[str, int], label_to_id_lower: dict[str, int], node_count: int):
        lines = [str(line or "").strip() for line in str(output_text or "").replace("\r", "").split("\n")]
        first = ""
        for line in lines:
            if not line:
                continue
            if re.match(r"(?i)^runtime\b", line):
                continue
            first = line
            break
        if not first:
            return None
        if re.search(r"no\s*path|path\s*not\s*found", first, flags=re.IGNORECASE):
            return None
        if ";" in first:
            left, right = first.split(";", 1)
            token = left.strip()
            if token.upper() in {"INF", "INFINITY"} or token == "-1":
                return None
            path_part = right.strip()
        else:
            path_part = first
        path_part = re.sub(r"\s*->\s*", " -> ", path_part)
        raw_tokens = [tok.strip() for tok in re.split(r"[,\s]+", path_part) if tok.strip()]
        path: list[int] = []
        for raw in raw_tokens:
            token = re.sub(r"^[\[\]{}()'\"`]+", "", raw)
            token = re.sub(r"[\[\]{}()'\"`,;:]+$", "", token).strip()
            if not token or token == "->":
                continue
            if token in label_to_id:
                path.append(label_to_id[token])
                continue
            lower = token.lower()
            if lower in label_to_id_lower:
                path.append(label_to_id_lower[lower])
                continue
            try:
                idx = int(token)
            except Exception:
                continue
            if 0 <= idx < node_count:
                path.append(idx)
        if len(path) < 2:
            return None
        compact: list[int] = []
        for value in path:
            if not compact or compact[-1] != value:
                compact.append(value)
        return compact if len(compact) >= 2 else None

    def _build_dijkstra_visualization_iteration(
        self,
        *,
        inputs: dict[str, Path],
        outputs: dict[str, str],
        label_lookup: dict[str, str],
        iteration: int,
        seed: int,
    ) -> dict:
        labels, label_to_id, label_to_id_lower, all_edges, start_label, target_label = self._parse_dijkstra_input_for_visualizer(inputs["dijkstra_file"])
        node_count = len(labels)
        max_nodes = 4000
        max_edges = 4000
        allowed_nodes = set(range(min(node_count, max_nodes)))
        truncated = node_count > max_nodes or len(all_edges) > max_edges
        limited_edges = sorted(all_edges)[:max_edges]
        limited_edge_set = set(limited_edges)
        nodes = [{"data": {"id": str(i), "label": str(labels[i] if i < len(labels) else i)}} for i in range(min(node_count, max_nodes))]
        edges = [{"data": {"id": f"{a}-{b}", "source": str(a), "target": str(b)}} for a, b in limited_edges]

        solutions: list[dict] = []
        for variant_id, text in outputs.items():
            path_nodes = self._extract_dijkstra_path_nodes(text, label_to_id, label_to_id_lower, node_count)
            if not path_nodes:
                continue
            highlight_nodes: list[int] = []
            for n in path_nodes:
                if n in allowed_nodes and (not highlight_nodes or highlight_nodes[-1] != n):
                    highlight_nodes.append(n)
            highlight_edges: list[str] = []
            for idx in range(len(path_nodes) - 1):
                ek = edge_key(path_nodes[idx], path_nodes[idx + 1])
                if ek is None or ek not in limited_edge_set:
                    continue
                highlight_edges.append(f"{ek[0]}-{ek[1]}")
            solutions.append(
                {
                    "name": label_lookup.get(variant_id, variant_id),
                    "mapping": [],
                    "highlight_nodes": highlight_nodes,
                    "highlight_edges": highlight_edges,
                    "path_labels": [labels[n] for n in path_nodes if 0 <= n < len(labels)],
                    "path_length": max(0, len(path_nodes) - 1),
                }
            )
            if len(solutions) >= VISUALIZER_SOLUTION_CAP:
                break

        fallback_nodes: list[str] = []
        if start_label is not None and start_label in label_to_id:
            fallback_nodes.append(str(label_to_id[start_label]))
        if target_label is not None and target_label in label_to_id:
            target_id = str(label_to_id[target_label])
            if target_id not in fallback_nodes:
                fallback_nodes.append(target_id)
        first = solutions[0] if solutions else None
        payload = {
            "algorithm": "dijkstra",
            "seed": int(seed),
            "iteration": int(iteration),
            "node_count": node_count,
            "edge_count": len(all_edges),
            "nodes": nodes,
            "edges": edges,
            "highlight_nodes": (first.get("highlight_nodes") if first else fallback_nodes),
            "highlight_edges": (first.get("highlight_edges") if first else []),
            "pattern_node_count": 0,
            "pattern_nodes": [],
            "pattern_edges": [],
            "solutions": solutions,
            "solution_cap_reached": len(solutions) >= VISUALIZER_SOLUTION_CAP,
            "no_solutions": len(solutions) == 0,
            "truncated": bool(truncated),
        }
        if start_label is not None:
            payload["start_label"] = start_label
            payload["start_node"] = start_label
        if target_label is not None:
            payload["target_label"] = target_label
            payload["end_node"] = target_label
        if first and first.get("path_labels"):
            payload["shortest_path"] = list(first.get("path_labels"))
            payload["shortest_path_length"] = int(max(0, len(first.get("path_labels")) - 1))
        elif first and isinstance(first.get("path_length"), int):
            payload["shortest_path_length"] = int(first.get("path_length"))
        return payload

    def _figure_for_tab(self, tab_key: str):
        mapping = {
            "runtime_2d": self.last_runtime_fig,
            "memory_2d": self.last_memory_fig,
            "runtime_3d": self.last_runtime_3d_fig,
            "memory_3d": self.last_memory_3d_fig,
        }
        return mapping.get(tab_key)

    def _build_figure_for_tab(self, tab_key: str, payload: dict, datapoints: list[dict]):
        if tab_key == "runtime_2d":
            return self._make_metric_2d_figure(payload, metric="runtime", datapoints=datapoints)
        if tab_key == "memory_2d":
            return self._make_metric_2d_figure(payload, metric="memory", datapoints=datapoints)
        if tab_key == "runtime_3d":
            return self._make_metric_3d_figure(payload, metric="runtime", datapoints=datapoints)
        if tab_key == "memory_3d":
            return self._make_metric_3d_figure(payload, metric="memory", datapoints=datapoints)
        return None

    def _open_graph_fullscreen(self, tab_key: str):
        if not self.last_plot_context:
            messagebox.showwarning(APP_TITLE, "No graph is available yet for this tab.")
            return
        payload = self.last_plot_context
        datapoints = self._collect_payload_datapoints(payload)
        fig = self._build_figure_for_tab(tab_key, payload, datapoints)
        if fig is None:
            messagebox.showwarning(APP_TITLE, "No graph is available yet for this tab.")
            return

        popup = tk.Toplevel(self)
        popup.title("Graph Fullscreen")
        popup.transient(self)
        popup.configure(background="#111111")
        def _close_popup(_evt=None):
            try:
                fig.clear()
            except Exception:
                pass
            popup.destroy()

        popup.bind("<Escape>", _close_popup)
        popup.protocol("WM_DELETE_WINDOW", _close_popup)
        try:
            popup.attributes("-fullscreen", True)
        except Exception:
            try:
                popup.state("zoomed")
            except Exception:
                pass

        top_bar = ttk.Frame(popup)
        top_bar.pack(fill=tk.X)
        ttk.Label(top_bar, text="Press Esc to exit fullscreen view").pack(side=tk.LEFT, padx=8, pady=6)
        ttk.Button(top_bar, text="Close", command=_close_popup).pack(side=tk.RIGHT, padx=8, pady=4)

        canvas = FigureCanvasTkAgg(fig, master=popup)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _save_graph_from_tab(self, tab_key: str):
        fig = self._figure_for_tab(tab_key)
        if fig is None:
            messagebox.showwarning(APP_TITLE, "No graph is available yet for this tab.")
            return

        is_3d = tab_key.endswith("_3d")
        style = self.plot3d_style_var.get().strip().lower()
        allow_stl = bool(
            is_3d
            and style == "surface"
            and self.last_plot_context
            and self.last_plot_context.get("run_config", {}).get("secondary_variable") is not None
        )
        filetypes = [
            ("PNG image", "*.png"),
            ("SVG image", "*.svg"),
            ("PDF document", "*.pdf"),
        ]
        if allow_stl:
            filetypes.append(("STL mesh (surface)", "*.stl"))
        target = filedialog.asksaveasfilename(
            title="Save Graph",
            defaultextension=".png",
            filetypes=filetypes,
        )
        if not target:
            return

        target_path = Path(target)
        suffix = target_path.suffix.lower()
        try:
            if suffix == ".stl":
                if not allow_stl:
                    raise ValueError("STL export is only available for 3D surface plots with two independent variables.")
                metric = "runtime" if tab_key == "runtime_3d" else "memory"
                if not self.last_plot_context or not self._save_surface_stl_for_metric(self.last_plot_context, target_path, metric):
                    raise ValueError("No plottable 3D surface data is available for STL export.")
            else:
                if suffix == ".png":
                    fig.savefig(target_path, dpi=150)
                else:
                    fig.savefig(target_path)
            self._append_log(f"Saved graph: {target_path}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Failed to save graph:\n{exc}")

    def _center_3d_view(self, metric: str):
        if metric == "runtime":
            fig = self.last_runtime_3d_fig
            canvas = self.runtime_3d_canvas
        else:
            fig = self.last_memory_3d_fig
            canvas = self.memory_3d_canvas
        if fig is None or canvas is None or not fig.axes:
            return
        ax = fig.axes[0]
        if not hasattr(ax, "view_init"):
            return
        ax.view_init(elev=DEFAULT_3D_ELEV, azim=DEFAULT_3D_AZIM)
        canvas.draw_idle()

    def _resolve_3d_variant_id(self, payload: dict):
        config = payload["run_config"]
        selected_label = self.plot3d_variant_var.get().strip()
        label_to_id = {label: vid for vid, label in config["selected_variant_labels"].items()}
        return label_to_id.get(selected_label, config.get("plot3d_variant"))

    def _save_surface_stl_for_metric(self, payload: dict, target_path: Path, metric: str) -> bool:
        config = payload["run_config"]
        if config["secondary_variable"] is None:
            return False
        variant_id = self._resolve_3d_variant_id(payload)
        if not variant_id:
            return False
        datapoints = self._collect_payload_datapoints(payload)
        built = self._build_3d_grid_for_variant(payload, variant_id, metric, datapoints)
        if built is None:
            return False
        xs, ys, z_grid = built
        triangles = []
        for yi in range(len(ys) - 1):
            for xi in range(len(xs) - 1):
                p00 = (xs[xi], ys[yi], z_grid[yi][xi])
                p10 = (xs[xi + 1], ys[yi], z_grid[yi][xi + 1])
                p01 = (xs[xi], ys[yi + 1], z_grid[yi + 1][xi])
                p11 = (xs[xi + 1], ys[yi + 1], z_grid[yi + 1][xi + 1])
                if all(math.isfinite(p[2]) for p in (p00, p10, p01, p11)):
                    triangles.append((p00, p10, p11))
                    triangles.append((p00, p11, p01))
        if not triangles:
            return False
        write_ascii_stl(target_path, f"{metric}_surface", triangles)
        return True

    def _write_session_json_streaming(self, payload: dict, json_path: Path):
        items_without_datapoints = [(k, v) for k, v in payload.items() if k != "datapoints"]
        with json_path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("{\n")
            if items_without_datapoints:
                for key, value in items_without_datapoints:
                    serialized = json.dumps(value, indent=2, default=serialize_for_json)
                    if "\n" in serialized:
                        serialized = serialized.replace("\n", "\n  ")
                    fh.write(f"  {json.dumps(key)}: {serialized},\n")
            fh.write('  "datapoints": [')
            first = True
            for row in self._iter_payload_datapoints(payload):
                row_json = json.dumps(row, default=serialize_for_json)
                if first:
                    fh.write("\n")
                    first = False
                else:
                    fh.write(",\n")
                fh.write(f"    {row_json}")
            if first:
                fh.write("]\n")
            else:
                fh.write("\n  ]\n")
            fh.write("}\n")

    def _save_exports(self, payload: dict, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "benchmark-session.json"
        csv_path = out_dir / "benchmark-session.csv"
        self._write_session_json_streaming(payload, json_path)

        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "variant_id", "variant_label", "x_value", "y_value", "runtime_median_ms", "runtime_stdev_ms", "runtime_samples_n",
                "memory_median_kb", "memory_stdev_kb", "memory_samples_n", "completed_iterations", "requested_iterations",
                "outlier_filter_mode", "outlier_filter_min_samples", "runtime_samples_total_n", "memory_samples_total_n",
                "runtime_samples_json", "memory_samples_json", "runtime_samples_raw_json", "memory_samples_raw_json", "seeds_json",
            ])
            for row in self._iter_payload_datapoints(payload):
                writer.writerow([
                    row["variant_id"],
                    row["variant_label"],
                    number_or_blank(row["x_value"]),
                    number_or_blank(row["y_value"]) if row["y_value"] is not None else "",
                    number_or_blank(row["runtime_median_ms"]),
                    number_or_blank(row["runtime_stdev_ms"]),
                    row["runtime_samples_n"],
                    number_or_blank(row["memory_median_kb"]),
                    number_or_blank(row["memory_stdev_kb"]),
                    row["memory_samples_n"],
                    row["completed_iterations"],
                    row["requested_iterations"],
                    row.get("outlier_filter_mode", payload.get("run_config", {}).get("outlier_filter", "none")),
                    row.get("outlier_filter_min_samples", payload.get("run_config", {}).get("outlier_filter_min_samples", DEFAULT_OUTLIER_MIN_SAMPLES)),
                    row.get("runtime_samples_total_n", row.get("runtime_samples_n", 0)),
                    row.get("memory_samples_total_n", row.get("memory_samples_n", 0)),
                    json.dumps(row.get("runtime_samples_ms", [])),
                    json.dumps(row.get("memory_samples_kb", [])),
                    json.dumps(row.get("runtime_samples_raw_ms", row.get("runtime_samples_ms", []))),
                    json.dumps(row.get("memory_samples_raw_kb", row.get("memory_samples_kb", []))),
                    json.dumps(row["seeds"]),
                ])

        if self.last_runtime_fig is not None:
            self.last_runtime_fig.savefig(out_dir / "runtime-2d.png", dpi=150)
            self.last_runtime_fig.savefig(out_dir / "runtime-2d.svg")
        if self.last_memory_fig is not None:
            self.last_memory_fig.savefig(out_dir / "memory-2d.png", dpi=150)
            self.last_memory_fig.savefig(out_dir / "memory-2d.svg")
        if self.last_runtime_3d_fig is not None:
            self.last_runtime_3d_fig.savefig(out_dir / "runtime-3d.png", dpi=150)
            self.last_runtime_3d_fig.savefig(out_dir / "runtime-3d.svg")
        if self.last_memory_3d_fig is not None:
            self.last_memory_3d_fig.savefig(out_dir / "memory-3d.png", dpi=150)
            self.last_memory_3d_fig.savefig(out_dir / "memory-3d.svg")

        self._maybe_save_surface_stl(payload, out_dir, metric="runtime")
        self._maybe_save_surface_stl(payload, out_dir, metric="memory")

    def _maybe_save_surface_stl(self, payload: dict, out_dir: Path, metric: str):
        config = payload["run_config"]
        if config["secondary_variable"] is None:
            return
        if self.plot3d_style_var.get().strip().lower() != "surface":
            return
        self._save_surface_stl_for_metric(payload, out_dir / f"{metric}-3d-surface.stl", metric)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--visualizer-webview-url", dest="visualizer_webview_url", default=None)
    parser.add_argument("--visualizer-webview-title", dest="visualizer_webview_title", default=APP_TITLE)
    parser.add_argument("--visualizer-webview-fullscreen", dest="visualizer_webview_fullscreen", default="0")
    args, _unknown = parser.parse_known_args()

    if args.visualizer_webview_url:
        fullscreen_flag = str(args.visualizer_webview_fullscreen).strip().lower() in {"1", "true", "yes", "on"}
        return run_visualizer_webview_window(
            url=str(args.visualizer_webview_url),
            title=str(args.visualizer_webview_title or APP_TITLE),
            fullscreen=fullscreen_flag,
        )

    headless_switches = {"--manifest", "--write-manifest", "--run", "--list-variants", "--list-datasets"}
    if args.headless or any(flag in sys.argv[1:] for flag in headless_switches):
        repo_root = Path(__file__).resolve().parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from desktop_runner.headless_runner import main as headless_main

        forwarded = [arg for arg in sys.argv[1:] if arg != "--headless"]
        return headless_main(forwarded)

    app = BenchmarkRunnerApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

