#!/usr/bin/env python3
"""Capstone desktop benchmark runner (cross-platform, one-file packaged app)."""

from __future__ import annotations

import csv
import concurrent.futures
import datetime as dt
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

APP_TITLE = "Capstone Benchmark Runner"
DEFAULT_WIDTH = 1500
DEFAULT_HEIGHT = 980
DEFAULT_DISCARDED_WARMUP_TRIALS = 5
DEFAULT_3D_ELEV = 30.0
# Keep x=min and y=min corner toward the viewer in the default isometric view.
DEFAULT_3D_AZIM = -135.0


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
    if len(stripped) == 1 and re.fullmatch(r"-?\d+", stripped[0]):
        return int(stripped[0])

    return None


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


def _default_solver_rows() -> list[dict]:
    return [
        {"variant_id": "vf3_baseline", "label": "VF3 Baseline", "family": "vf3", "role": "baseline"},
        {"variant_id": "vf3_chatgpt", "label": "VF3 Chatgpt", "family": "vf3", "role": "variant", "llm_key": "chatgpt", "llm_label": "Chatgpt"},
        {"variant_id": "vf3_gemini", "label": "VF3 Gemini", "family": "vf3", "role": "variant", "llm_key": "gemini", "llm_label": "Gemini"},
        {"variant_id": "glasgow_baseline", "label": "Glasgow Baseline", "family": "glasgow", "role": "baseline"},
        {"variant_id": "glasgow_chatgpt", "label": "Glasgow Chatgpt", "family": "glasgow", "role": "variant", "llm_key": "chatgpt", "llm_label": "Chatgpt"},
        {"variant_id": "glasgow_gemini", "label": "Glasgow Gemini", "family": "glasgow", "role": "variant", "llm_key": "gemini", "llm_label": "Gemini"},
        {"variant_id": "dijkstra_baseline", "label": "Dijkstra Baseline", "family": "dijkstra", "role": "baseline"},
        {"variant_id": "dijkstra_chatgpt", "label": "Dijkstra Chatgpt", "family": "dijkstra", "role": "variant", "llm_key": "chatgpt", "llm_label": "Chatgpt"},
        {"variant_id": "dijkstra_gemini", "label": "Dijkstra Gemini", "family": "dijkstra", "role": "variant", "llm_key": "gemini", "llm_label": "Gemini"},
    ]


def _load_solver_rows_from_manifest() -> list[dict]:
    manifest_path = resource_root() / "binaries" / "solver_variants.json"
    if not manifest_path.is_file():
        return _default_solver_rows()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_solver_rows()
    rows = payload.get("solvers")
    if not isinstance(rows, list):
        return _default_solver_rows()
    normalized: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        variant_id = str(row.get("variant_id") or "").strip()
        family = str(row.get("family") or "").strip().lower()
        label = str(row.get("label") or "").strip()
        if not variant_id or family not in {"dijkstra", "vf3", "glasgow"}:
            continue
        normalized.append(
            {
                "variant_id": variant_id,
                "label": label or variant_id,
                "family": family,
                "role": str(row.get("role") or "").strip().lower() or "variant",
                "llm_key": str(row.get("llm_key") or "").strip().lower() or None,
                "llm_label": str(row.get("llm_label") or "").strip() or None,
                "binary_name": str(row.get("binary_name") or "").strip() or variant_id,
            }
        )
    if not normalized:
        return _default_solver_rows()
    return normalized


def _build_solver_variants_and_binary_map() -> tuple[list[SolverVariant], dict[str, Path]]:
    root = resource_root()
    binaries_dir = root / "binaries"
    exe_suffix = ".exe" if sys.platform.startswith("win") else ""
    rows = _load_solver_rows_from_manifest()
    variants: list[SolverVariant] = []
    binary_map: dict[str, Path] = {}
    for row in rows:
        variant_id = str(row.get("variant_id") or "").strip()
        family = str(row.get("family") or "").strip().lower()
        if not variant_id or family not in {"dijkstra", "vf3", "glasgow"}:
            continue
        tab_id = "shortest_path" if family == "dijkstra" else "subgraph"
        label = str(row.get("label") or variant_id)
        variants.append(SolverVariant(variant_id, label, tab_id, family))
        binary_name = str(row.get("binary_name") or variant_id).strip() or variant_id
        binary_map[variant_id] = binaries_dir / f"{binary_name}{exe_suffix}"
    variants.sort(key=lambda item: (item.tab_id, item.family, item.variant_id != f"{item.family}_baseline", item.label.lower()))
    return variants, binary_map


SOLVER_VARIANTS, _DEFAULT_BINARY_PATH_MAP = _build_solver_variants_and_binary_map()


def build_binary_path_map() -> dict[str, Path]:
    return dict(_DEFAULT_BINARY_PATH_MAP)


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


def generate_dijkstra_inputs(out_dir: Path, n: int, density: float, seed: int) -> Path:
    rng = random.Random(seed)
    labels = [f"v{i}" for i in range(n)]
    edges = generate_directed_edges(n, rng, density)
    path = out_dir / "dijkstra_generated.csv"
    write_dijkstra_csv(path, edges, labels)
    return path


def generate_subgraph_inputs(out_dir: Path, n: int, k: int, density: float, seed: int):
    if k >= n:
        raise ValueError("k must be smaller than N")
    rng = random.Random(seed)
    target_adj = generate_adjacency(n, rng, density)
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
    return {
        "vf_pattern": vf_pattern,
        "vf_target": vf_target,
        "lad_pattern": lad_pattern,
        "lad_target": lad_target,
    }

class BenchmarkRunnerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}")
        self.minsize(1200, 840)

        self.binary_paths = build_binary_path_map()
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
        self.run_timer_deadline_monotonic: float | None = None
        self.run_timer_after_id: str | None = None
        self.live_log_lines: dict[str, str] = {}
        self.drilldown_popup: tk.Toplevel | None = None
        self.drilldown_popup_mode: str | None = None
        self.drilldown_popup_point_key: tuple | None = None
        self.drilldown_highlight_artist = None
        self.drilldown_highlight_canvas: FigureCanvasTkAgg | None = None

        self._build_state()
        self._build_ui()
        self._on_tab_changed()
        self.after(0, self._apply_default_window_state)
        self.after(120, self._set_default_body_split)

    def _build_state(self):
        self.tab_id_var = tk.StringVar(value="subgraph")
        self.iterations_var = tk.StringVar(value="5")
        self.seed_var = tk.StringVar(value="")
        self.run_mode_var = tk.StringVar(value="threshold")
        self.time_limit_minutes_var = tk.StringVar(value="10")
        self.solver_timeout_seconds_var = tk.StringVar(value="0")
        self.detected_logical_cores = int(psutil.cpu_count(logical=True) or os.cpu_count() or 1)
        self.parallel_enabled_var = tk.BooleanVar(value=self.detected_logical_cores > 1)
        default_workers = 1 if self.detected_logical_cores <= 1 else min(8, self.detected_logical_cores)
        self.max_workers_var = tk.StringVar(value=str(default_workers))
        self.delete_generated_inputs_var = tk.BooleanVar(value=True)
        self.plot3d_style_var = tk.StringVar(value="surface")
        self.plot3d_variant_var = tk.StringVar(value="")
        self.show_stddev_var = tk.BooleanVar(value=True)
        self.show_regression_var = tk.BooleanVar(value=False)
        self.log_x_scale_var = tk.BooleanVar(value=False)
        self.log_y_scale_var = tk.BooleanVar(value=False)
        self.failure_policy_var = tk.StringVar(value="stop")
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

    def _build_ui(self):
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        self._scroll_canvas = tk.Canvas(outer, highlightthickness=0)
        v_scroll = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=self._scroll_canvas.yview)
        h_scroll = ttk.Scrollbar(outer, orient=tk.HORIZONTAL, command=self._scroll_canvas.xview)
        self._scroll_canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        self._scroll_canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

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

        ttk.Label(left_col, text="Iterations per datapoint").grid(row=0, column=0, sticky="w")
        ttk.Entry(left_col, textvariable=self.iterations_var, width=10).grid(row=0, column=1, padx=(8, 0), sticky="w")

        ttk.Label(left_col, text="Stop Mode").grid(row=1, column=0, pady=(8, 0), sticky="w")
        mode_row = ttk.Frame(left_col)
        mode_row.grid(row=1, column=1, pady=(8, 0), padx=(8, 0), sticky="w")
        ttk.Radiobutton(mode_row, text="Threshold", variable=self.run_mode_var, value="threshold", command=self._on_run_mode_changed).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_row, text="Timed", variable=self.run_mode_var, value="timed", command=self._on_run_mode_changed).pack(side=tk.LEFT, padx=(8, 0))
        self.parallel_check = ttk.Checkbutton(
            left_col,
            text="Enable Multi-Core",
            variable=self.parallel_enabled_var,
            command=self._on_parallel_settings_changed,
        )
        self.parallel_check.grid(row=2, column=0, columnspan=2, pady=(8, 0), sticky="w")
        ttk.Checkbutton(
            left_col,
            text="Delete generated inputs after datapoint",
            variable=self.delete_generated_inputs_var,
        ).grid(row=3, column=0, columnspan=2, pady=(8, 0), sticky="w")

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
            foreground="#555555",
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

        sweep = ttk.LabelFrame(settings_row, text="Independent Variables", padding=10)
        sweep.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ttk.Label(
            sweep,
            text="Select up to two variables to sweep. For unselected variables, Start is treated as the fixed value.",
        ).grid(row=0, column=0, columnspan=5, sticky="w", padx=4, pady=(0, 8))
        headers = ["Use", "Variable", "Start", "End", "Step"]
        for col, header in enumerate(headers):
            ttk.Label(sweep, text=header, font=("Segoe UI", 9, "bold")).grid(row=1, column=col, sticky="w", padx=4, pady=(0, 6))

        self.sweep_rows: dict[str, dict[str, tk.Widget]] = {}
        ordered = [("n", "N"), ("density", "Density"), ("k", "k % of N")]
        for i, (var_id, label) in enumerate(ordered, start=2):
            use_cb = ttk.Checkbutton(sweep, variable=self.var_selected[var_id], command=self._on_variable_selection_changed)
            use_cb.grid(row=i, column=0, padx=4, sticky="w")
            ttk.Label(sweep, text=label).grid(row=i, column=1, padx=4, sticky="w")
            start_entry = ttk.Entry(sweep, textvariable=self.var_start[var_id], width=12)
            start_entry.grid(row=i, column=2, padx=4, sticky="w")
            end_entry = ttk.Entry(sweep, textvariable=self.var_end[var_id], width=12)
            end_entry.grid(row=i, column=3, padx=4, sticky="w")
            step_entry = ttk.Entry(sweep, textvariable=self.var_step[var_id], width=12)
            step_entry.grid(row=i, column=4, padx=4, sticky="w")
            self.sweep_rows[var_id] = {
                "use_cb": use_cb,
                "start": start_entry,
                "end": end_entry,
                "step": step_entry,
            }

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
        self.log_box.tag_configure("error", foreground="#B00020")
        self.log_box.tag_configure("warn", foreground="#9A6700")
        self.log_box.tag_configure("success", foreground="#0A7D32")
        self.log_box.tag_configure("notice", foreground="#0B5CAD")
        self.log_box.configure(state=tk.DISABLED)
        body.add(log_container, weight=1)

        chart_panel = ttk.Notebook(body)
        self.chart_panel = chart_panel
        body.add(chart_panel, weight=1)

        runtime_tab = ttk.Frame(chart_panel)
        memory_tab = ttk.Frame(chart_panel)
        runtime_3d_tab = ttk.Frame(chart_panel)
        memory_3d_tab = ttk.Frame(chart_panel)
        chart_panel.add(runtime_tab, text="Runtime 2D")
        chart_panel.add(memory_tab, text="Memory 2D")
        chart_panel.add(runtime_3d_tab, text="Runtime 3D")
        chart_panel.add(memory_3d_tab, text="Memory 3D")

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

    def _apply_default_window_state(self):
        try:
            self.attributes("-fullscreen", True)
            self.bind("<Escape>", lambda _evt: self.attributes("-fullscreen", False))
            self.bind("<F11>", lambda _evt: self.attributes("-fullscreen", not bool(self.attributes("-fullscreen"))))
            return
        except Exception:
            pass
        try:
            self.state("zoomed")
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

    def _build_variant_section(self, parent: ttk.Frame, tab_id: str):
        container = ttk.Frame(parent, padding=8)
        container.pack(fill=tk.X)
        ttk.Label(container, text="Check one or more variants in this tab, or use Check All.").pack(fill=tk.X, pady=(0, 6))
        tools = ttk.Frame(container)
        tools.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(tools, text="Check All", command=lambda t=tab_id: self._set_all_variants(t, True)).pack(side=tk.LEFT)
        ttk.Button(tools, text="Clear All", command=lambda t=tab_id: self._set_all_variants(t, False)).pack(side=tk.LEFT, padx=(8, 0))

        vars_frame = ttk.Frame(container)
        vars_frame.pack(fill=tk.X)
        variants = [v for v in SOLVER_VARIANTS if v.tab_id == tab_id]
        if not variants:
            return

        families = list(dict.fromkeys(v.family for v in variants))
        role_rank = {"baseline": 0, "chatgpt": 1, "gemini": 2}

        def role_key(variant: SolverVariant):
            token = variant.variant_id.rsplit("_", 1)[-1].strip().lower()
            if token in role_rank:
                return token
            label_lower = variant.label.lower()
            if "baseline" in label_lower:
                return "baseline"
            if "chatgpt" in label_lower:
                return "chatgpt"
            if "gemini" in label_lower:
                return "gemini"
            return token

        role_keys = sorted({role_key(v) for v in variants}, key=lambda r: (role_rank.get(r, 99), r))
        by_family_role = {(v.family, role_key(v)): v for v in variants}

        ttk.Label(vars_frame, text="Variant", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, padx=(0, 8), pady=(0, 6), sticky="w")
        for col, family in enumerate(families, start=1):
            family_label = family.upper() if len(family) <= 5 else family.title()
            ttk.Label(vars_frame, text=family_label, font=("Segoe UI", 9, "bold")).grid(row=0, column=col, padx=(0, 12), pady=(0, 6), sticky="w")

        for row, role in enumerate(role_keys, start=1):
            role_label = role.upper() if role.lower() == "chatgpt" else role.title()
            ttk.Label(vars_frame, text=role_label).grid(row=row, column=0, padx=(0, 8), pady=(0, 6), sticky="w")
            for col, family in enumerate(families, start=1):
                variant = by_family_role.get((family, role))
                if variant is None:
                    ttk.Label(vars_frame, text="-", foreground="#888888").grid(row=row, column=col, padx=(0, 12), pady=(0, 6), sticky="w")
                    continue
                cb = ttk.Checkbutton(
                    vars_frame,
                    text="",
                    variable=self.variant_checks[variant.variant_id],
                    command=self._on_variants_changed,
                )
                cb.grid(row=row, column=col, padx=(0, 12), pady=(0, 6), sticky="w")

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

    def _append_log(self, text: str, level: str = "info"):
        self.log_box.configure(state=tk.NORMAL)
        auto_follow = self._log_should_autoscroll()
        tag = None
        if level in {"error", "warn", "success", "notice"}:
            tag = level
        insert_at = self._first_live_log_index_locked()
        if insert_at is None:
            insert_at = tk.END
        if tag is not None:
            self.log_box.insert(insert_at, text + "\n", (tag,))
        else:
            self.log_box.insert(insert_at, text + "\n")
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
            tag = (level,) if level in {"error", "warn", "success", "notice"} else ()
            if tag:
                self.log_box.insert(mark_name, text + "\n", tag)
            else:
                self.log_box.insert(mark_name, text + "\n")
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

    def _clear_graphs(self, announce: bool = False):
        had_graphs = any([
            self.runtime_canvas is not None,
            self.memory_canvas is not None,
            self.runtime_3d_canvas is not None,
            self.memory_3d_canvas is not None,
            self.last_runtime_fig is not None,
            self.last_memory_fig is not None,
            self.last_runtime_3d_fig is not None,
            self.last_memory_3d_fig is not None,
        ])

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

        self._clear_drilldown()
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
        seeds = list(row.get("seeds") or [])
        lines = [
            "Datapoint Drilldown",
            f"Metric: {metric}",
            f"Variant: {row.get('variant_label', row.get('variant_id', 'unknown'))}",
            f"X value: {number_or_blank(x_val) if x_val is not None else 'n/a'}",
            f"Y value: {number_or_blank(y_val) if y_val is not None else 'n/a'}",
            "",
            f"Runtime median (ms): {number_or_blank(row.get('runtime_median_ms'))}",
            f"Runtime stdev (ms): {number_or_blank(row.get('runtime_stdev_ms'))}",
            f"Runtime samples: {len(runtime_samples)}",
            f"Runtime samples raw: {json.dumps(runtime_samples)}",
            "",
            f"Memory median (KiB): {number_or_blank(row.get('memory_median_kb'))}",
            f"Memory stdev (KiB): {number_or_blank(row.get('memory_stdev_kb'))}",
            f"Memory samples: {len(memory_samples)}",
            f"Memory samples raw: {json.dumps(memory_samples)}",
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

    def _selected_variants_for_current_tab(self):
        tab_id = self.tab_id_var.get()
        return [
            variant
            for variant in SOLVER_VARIANTS
            if variant.tab_id == tab_id and self.variant_checks[variant.variant_id].get()
        ]

    def _format_run_input_segment(self, config: dict, var_id: str) -> str:
        specs = config.get("input_specs", {})
        spec = specs.get(var_id)
        label = axis_label(var_id)
        if spec is None:
            return f"{label}=n/a"
        selected = bool(spec.get("selected"))
        start = spec.get("start")
        end = spec.get("end")
        step = spec.get("step")
        if selected:
            if config.get("run_mode") == "timed":
                return (
                    f"{label} start={format_point_value(var_id, float(start))} "
                    f"step={format_step_value(var_id, None if step is None else float(step))} (timed)"
                )
            return (
                f"{label} {format_point_value(var_id, float(start))}->{format_point_value(var_id, float(end))} "
                f"step={format_step_value(var_id, None if step is None else float(step))}"
            )
        return f"{label} fixed={format_point_value(var_id, float(start))}"

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
                integer_mode = var_id == "n"
                start_raw = self.var_start[var_id].get().strip()
                step_raw = self.var_step[var_id].get().strip()
                end_raw = self.var_end[var_id].get().strip()
                if start_raw == "":
                    raise ValueError(f"Start is required for {axis_label(var_id)}.")
                if step_raw == "":
                    raise ValueError(f"Step is required for {axis_label(var_id)}.")
                if run_mode != "timed" and end_raw == "":
                    raise ValueError(f"End is required for {axis_label(var_id)}.")
                if var_id == "n":
                    start = float(parse_int(start_raw, f"{axis_label(var_id)} start", minimum=1))
                    step = float(parse_int(step_raw, f"{axis_label(var_id)} step", minimum=1))
                    end = float(parse_int(end_raw, f"{axis_label(var_id)} end", minimum=1)) if run_mode != "timed" else start
                elif var_id == "density":
                    start = parse_float(start_raw, f"{axis_label(var_id)} start", minimum=0.000001, maximum=1.0)
                    step = parse_float(step_raw, f"{axis_label(var_id)} step", minimum=0.000001, maximum=1.0)
                    end = parse_float(end_raw, f"{axis_label(var_id)} end", minimum=0.000001, maximum=1.0) if run_mode != "timed" else start
                else:
                    start = parse_float(start_raw, f"{axis_label(var_id)} start", minimum=0.000001, maximum=100.0)
                    step = parse_float(step_raw, f"{axis_label(var_id)} step", minimum=0.000001, maximum=100.0)
                    end = parse_float(end_raw, f"{axis_label(var_id)} end", minimum=0.000001, maximum=100.0) if run_mode != "timed" else start
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
                        for v in values:
                            if v <= 0 or v > 100:
                                raise ValueError("k % of N values must be in (0, 100].")
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
                    raise ValueError(f"Start is required for {axis_label(var_id)}.")
                if var_id == "n":
                    fixed_values[var_id] = float(parse_int(start_raw, f"{axis_label(var_id)} start", minimum=1))
                elif var_id == "density":
                    fixed_values[var_id] = parse_float(start_raw, f"{axis_label(var_id)} start", minimum=0.000001, maximum=1.0)
                else:
                    fixed_values[var_id] = parse_float(start_raw, f"{axis_label(var_id)} start", minimum=0.000001, maximum=100.0)
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
                k_percent = float(timed_probe["k"])
                if k_percent <= 0 or k_percent > 100:
                    raise ValueError("k % of N must be in (0, 100].")
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
                    k_percent = float(point["k"])
                    if k_percent <= 0 or k_percent > 100:
                        raise ValueError("k % of N must be in (0, 100].")
                    # k is defined as a percentage of N; round and clamp to a valid pattern size.
                    k_nodes = int(round((k_percent / 100.0) * n_nodes))
                    k_nodes = max(2, min(n_nodes - 1, k_nodes))
                    point["k_nodes"] = k_nodes

        style = self.plot3d_style_var.get().strip().lower()
        if style not in {"surface", "wireframe", "scatter"}:
            style = "surface"
        selected_variant_label = self.plot3d_variant_var.get().strip()
        variant_lookup = {variant.label: variant.variant_id for variant in selected_variants}
        variant_for_3d = variant_lookup.get(selected_variant_label)
        if not variant_for_3d and selected_variants:
            variant_for_3d = selected_variants[0].variant_id

        return {
            "tab_id": tab_id,
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
        self.session_output_dir = make_session_output_dir()
        self.last_run_payload = None
        self._clear_graphs(announce=False)
        self._clear_drilldown()
        self._append_log("Cleared previous graphs for new run.", level="notice")
        deadline = self._start_run_timer(config["time_limit_minutes"] if config["run_mode"] == "timed" else None)
        config["deadline_monotonic"] = deadline
        self._append_log(f"Output directory: {self.session_output_dir}")
        datapoints_label = str(len(config["datapoints"])) if config["run_mode"] != "timed" else "unbounded (timed)"
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
        self._append_log(
            f"Starting run | tab={config['tab_id']} | variants={len(config['selected_variants'])} | "
            f"datapoints={datapoints_label} | iterations={config['iterations']} | "
            f"parallel={parallel_mode} workers={config['max_workers']} cores={config['detected_logical_cores']} | "
            f"solver_timeout={timeout_mode} | "
            f"failure_policy={failure_mode} retries={retry_count} timeout_policy={timeout_mode_policy} | "
            f"delete_generated_inputs={'on' if config.get('delete_generated_inputs') else 'off'} | "
            f"{variable_segments}"
        )

        self.run_btn.configure(state=tk.DISABLED)
        self.abort_btn.configure(state=tk.NORMAL)
        self.pause_btn.configure(state=tk.NORMAL, text="Pause")
        self.open_dir_btn.configure(state=tk.NORMAL)
        self.save_btn.configure(state=tk.DISABLED)

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
        warmups = int(config.get("warmup_trials", 0)) * variants
        mode = config["run_mode"]
        lines = [
            "Run Estimate",
            f"Tab: {config['tab_id']}",
            f"Variants: {variants}",
            f"Iterations per datapoint: {iterations}",
            f"Discarded warm-up solver calls: {warmups}",
        ]
        if mode == "threshold":
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
            return max(0.000001, min(100.0, float(value)))
        return float(value)

    def _timed_upper_bound(self, var_id: str) -> float | None:
        if var_id == "density":
            return 1.0
        if var_id == "k":
            return 100.0
        return None

    def _timed_max_index(self, config: dict, var_id: str) -> int | None:
        upper = self._timed_upper_bound(var_id)
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
            k_percent = max(0.000001, min(100.0, float(point["k"])))
            point["n"] = float(n_nodes)
            point["density"] = density_value
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
        solver_timeout_seconds = config.get("solver_timeout_seconds")
        warmup_trials = int(max(0, config.get("warmup_trials", 0)))
        failure_policy = str(config.get("failure_policy", "stop")).strip().lower()
        retry_failed_trials = int(max(0, config.get("retry_failed_trials", 0)))
        timeout_as_missing = bool(config.get("timeout_as_missing", True))
        parallel_workers = int(max(1, config.get("max_workers", 1)))
        executor: concurrent.futures.ThreadPoolExecutor | None = concurrent.futures.ThreadPoolExecutor(
            max_workers=parallel_workers,
            thread_name_prefix="solver",
        )

        if config["run_mode"] == "timed":
            bounded_vars = [v for v in (config["primary_var"], config["secondary_var"]) if v in {"density", "k"}]
            if bounded_vars:
                bounded_labels = ", ".join(axis_label(v) for v in bounded_vars)
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
                        if config["tab_id"] == "shortest_path":
                            generated_warmup = {"dijkstra_file": generate_dijkstra_inputs(warmup_dir, n_value, density_value, warmup_seed)}
                        else:
                            generated_warmup = generate_subgraph_inputs(warmup_dir, n_value, k_value, density_value, warmup_seed)
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
                for variant_id in selected_variants:
                    runtimes = state["samples_runtime"][variant_id]
                    memories = state["samples_memory"][variant_id]
                    if not runtimes and not memories:
                        if timed_out or aborted:
                            continue
                    row = {
                        "variant_id": variant_id,
                        "variant_label": config["selected_variant_labels"].get(variant_id, variant_id),
                        "x_value": x_value,
                        "y_value": y_value,
                        "runtime_median_ms": median_or_none(runtimes),
                        "runtime_stdev_ms": safe_stdev(runtimes),
                        "runtime_samples_n": len(runtimes),
                        "memory_median_kb": median_or_none(memories),
                        "memory_stdev_kb": safe_stdev(memories),
                        "memory_samples_n": len(memories),
                        "completed_iterations": int(state["completed_iterations"]),
                        "requested_iterations": config["iterations"],
                        "seeds": list(state["seed_records"][variant_id]),
                        "runtime_samples_ms": [float(v) for v in runtimes],
                        "memory_samples_kb": [float(v) for v in memories],
                    }
                    datapoints_stream_fh.write(json.dumps(row, default=serialize_for_json) + "\n")
                    streamed_datapoint_rows += 1

                combined_runtime_samples: list[float] = []
                for variant_id in selected_variants:
                    combined_runtime_samples.extend(state["samples_runtime"][variant_id])
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
                        point_label = f"{config['primary_var']}={format_point_value(config['primary_var'], x_value)}"
                        if config["secondary_var"] is not None and y_value is not None:
                            point_label += f", {config['secondary_var']}={format_point_value(config['secondary_var'], y_value)}"
                        state = {
                            "point_idx": point_idx,
                            "point_label": point_label,
                            "x_value": x_value,
                            "y_value": y_value,
                            "point_dir": generated_root / f"point_{point_idx + 1:05d}",
                            "samples_runtime": {variant_id: [] for variant_id in selected_variants},
                            "samples_memory": {variant_id: [] for variant_id in selected_variants},
                            "seed_records": {variant_id: [] for variant_id in selected_variants},
                            "submitted_trials": 0,
                            "completed_trials": 0,
                            "submission_done": False,
                            "completed_iterations": 0,
                            "iter_pending": {iter_idx: set(selected_variants) for iter_idx in range(config["iterations"])},
                            "iter_solution_counts": {iter_idx: {} for iter_idx in range(config["iterations"])},
                            "iter_success_count": {iter_idx: 0 for iter_idx in range(config["iterations"])},
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
                        point_dir = cursor["state"]["point_dir"]
                        iter_dir = point_dir / f"iter_{iter_idx + 1:03d}"
                        iter_dir.mkdir(parents=True, exist_ok=True)
                        n_value = int(round(point["n"]))
                        density_value = float(point["density"])
                        k_value = int(round(point.get("k_nodes", 1)))
                        if config["tab_id"] == "shortest_path":
                            generated = {"dijkstra_file": generate_dijkstra_inputs(iter_dir, n_value, density_value, iter_seed)}
                        else:
                            generated = generate_subgraph_inputs(iter_dir, n_value, k_value, density_value, iter_seed)
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
                    runtime_ms = 0.0
                    peak_kb = 0.0
                    handled_failure = False

                    try:
                        runtime_ms, peak_kb, solution_count = future.result()
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
                        if solution_count is not None:
                            state["iter_solution_counts"][iter_idx][variant_id] = solution_count
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
            )
            self.last_run_payload = payload
            self.last_plot_context = payload
            self.after(0, lambda: self._render_plots(payload))
            self._save_exports(payload, self.session_output_dir)

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
            self.save_btn.configure(state=tk.NORMAL)

    def _run_solver_variant(
        self,
        variant_id: str,
        generated: dict[str, Path],
        heartbeat_label: str | None = None,
        solver_timeout_seconds: float | None = None,
    ):
        binary = self.binary_paths[variant_id]
        if not binary.exists():
            raise FileNotFoundError(f"Missing binary for {variant_id}: {binary}")

        if variant_id.startswith("dijkstra_"):
            command = [str(binary), str(generated["dijkstra_file"])]
        elif variant_id.startswith("vf3_"):
            if variant_id == "vf3_baseline":
                # Match the web runner's stable baseline invocation on generated VF inputs.
                command = [str(binary), "-u", "-r", "0", "-e", str(generated["vf_pattern"]), str(generated["vf_target"])]
            else:
                command = [str(binary), "--non-induced", str(generated["vf_pattern"]), str(generated["vf_target"])]
        elif variant_id.startswith("glasgow_"):
            if variant_id == "glasgow_baseline":
                command = [str(binary), "--count-solutions", "--format", "vertexlabelledlad", str(generated["lad_pattern"]), str(generated["lad_target"])]
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
        solution_count = None
        if variant_id.startswith("vf3_") or variant_id.startswith("glasgow_"):
            solution_count = parse_solution_count(stdout_text + "\n" + stderr_text)
        return runtime_ms, peak_kb, solution_count

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
    ):
        duration_ms = (ended_at - started_at).total_seconds() * 1000.0

        return {
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
                "delete_generated_inputs": config.get("delete_generated_inputs"),
                "warmup_trials": config.get("warmup_trials", 0),
            },
            "datapoints": [],
            "datapoints_path": str(datapoints_path),
            "streamed_datapoint_rows": int(streamed_datapoint_rows),
        }

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

    def _make_metric_2d_figure(self, payload: dict, metric: str, datapoints: list[dict]):
        fig = Figure(figsize=(7.5, 5.0), dpi=100)
        ax = fig.add_subplot(111)
        config = payload["run_config"]
        primary_var = config["primary_variable"]
        secondary_var = config["secondary_variable"]
        x_values_full = list(config["var_ranges"].get(primary_var, []))

        selected_variants = config["selected_variants"]
        label_map = config["selected_variant_labels"]
        show_stddev = bool(self.show_stddev_var.get())
        show_regression = bool(self.show_regression_var.get())
        use_log_x = bool(self.log_x_scale_var.get())
        use_log_y = bool(self.log_y_scale_var.get())
        pick_map = {}
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
            if show_stddev:
                container = ax.errorbar(xs, ys, yerr=errs, marker="o", capsize=3, label=label)
                line_color = None
                if getattr(container, "lines", None):
                    first_line = container.lines[0]
                    line_color = first_line.get_color() if first_line is not None else None
                    line_for_pick = first_line
            else:
                plotted = ax.plot(xs, ys, marker="o", label=label)
                line_color = plotted[0].get_color() if plotted else None
                if plotted:
                    line_for_pick = plotted[0]

            if line_for_pick is not None:
                try:
                    line_for_pick.set_picker(5)
                    pick_map[line_for_pick] = {
                        "rows": list(rows),
                        "xs": list(xs),
                        "ys": list(ys),
                    }
                except Exception:
                    pass

            if show_regression:
                reg_line = linear_regression_line(xs, ys)
                if reg_line is not None:
                    reg_x, reg_y = reg_line
                    ax.plot(
                        reg_x,
                        reg_y,
                        linestyle="--",
                        linewidth=1.2,
                        alpha=0.9,
                        color=line_color,
                        label=f"{label} trend",
                    )

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
                        series_name = f"{label_map.get(variant_id, variant_id)} | {axis_label(secondary_var)}={format_point_value(secondary_var, y_const)}"
                        plot_series(xs, ys, errs, series_name, rows)

        ax.set_xlabel(axis_label(primary_var))
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
        handles, _labels = ax.get_legend_handles_labels()
        if handles:
            ncols = 1 if len(handles) <= 3 else 2
            legend_title = None
            if show_stddev and show_regression:
                legend_title = "Error bars: +/-1 SD | Dashed: linear trend"
            elif show_stddev:
                legend_title = "Error bars: +/-1 SD"
            elif show_regression:
                legend_title = "Dashed lines: linear trend"
            ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, -0.22),
                ncol=ncols,
                fontsize=8,
                title=legend_title,
            )
            fig.tight_layout(rect=(0.0, 0.08, 1.0, 1.0))
        else:
            fig.tight_layout()
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
        ax.set_xlabel(axis_label(primary_var))
        ax.set_ylabel(axis_label(secondary_var))
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

    def _repaint_existing_plots(self):
        if not self.last_plot_context:
            return
        self._render_plots(self.last_plot_context)

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
            if not inds:
                continue
            idx = int(inds[0])
            rows = list(payload.get("rows", []))
            xs = list(payload.get("xs", []))
            ys = list(payload.get("ys", []))
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

        if mode == "hover" and self.drilldown_popup_mode == "click":
            return

        if mode == "hover" and self.drilldown_popup_mode == "hover" and self.drilldown_popup_point_key == key and self.drilldown_popup is not None:
            try:
                self.drilldown_popup.geometry(f"+{x_root + 16}+{y_root + 16}")
            except Exception:
                pass
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
                bg="#fffbe6",
                fg="#222222",
                relief="solid",
                bd=1,
                padx=8,
                pady=6,
                font=("Consolas", 9),
            )
            label.pack(fill=tk.BOTH, expand=True)
            popup.geometry(f"+{x_root + 16}+{y_root + 16}")
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
            body.configure(state=tk.DISABLED)
            popup.geometry(f"+{x_root + 20}+{y_root + 20}")

        self.drilldown_popup = popup
        self.drilldown_popup_mode = mode
        self.drilldown_popup_point_key = key
        self._set_drilldown_highlight(info["ax"], info["canvas"], info["x"], info["y"])

    def _on_2d_motion(self, event, metric: str):
        if self.drilldown_popup_mode == "click":
            return
        info = self._locate_2d_row_from_event(event, metric)
        if info is None:
            if self.drilldown_popup_mode == "hover":
                self._clear_drilldown()
            return
        self._open_drilldown_popup(info, mode="hover", event=event)

    def _on_2d_leave(self, _event, metric: str):
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
                "runtime_samples_json", "memory_samples_json", "seeds_json",
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
                    json.dumps(row.get("runtime_samples_ms", [])),
                    json.dumps(row.get("memory_samples_kb", [])),
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
    app = BenchmarkRunnerApp()
    app.mainloop()


if __name__ == "__main__":
    main()

