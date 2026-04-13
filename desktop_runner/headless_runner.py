
#!/usr/bin/env python3
"""Headless benchmark CLI and manifest runner."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from desktop_runner import app as app_mod
from utilities import generate_graphs as generator_mod
from utilities.benchmark_provenance import collect_runtime_provenance

MANIFEST_SCHEMA_VERSION = "capstone-benchmark-manifest-v1"
SESSION_SCHEMA_VERSION = "desktop-benchmark-v2"
TRIAL_SCHEMA_VERSION = "desktop-benchmark-trial-v1"
DATASET_INFO_SCHEMA_VERSION = "desktop-dataset-selection-v1"

PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "smoke": {
        "iterations": 1,
        "solver_timeout_seconds": 30.0,
        "failure_policy": "stop",
        "retry_failed_trials": 0,
        "timeout_as_missing": True,
        "outlier_filter": "none",
        "delete_generated_inputs": True,
    },
    "standard": {
        "iterations": 3,
        "solver_timeout_seconds": 120.0,
        "failure_policy": "continue",
        "retry_failed_trials": 0,
        "timeout_as_missing": True,
        "outlier_filter": "mad",
        "delete_generated_inputs": True,
    },
    "full": {
        "iterations": 7,
        "solver_timeout_seconds": 300.0,
        "failure_policy": "continue",
        "retry_failed_trials": 1,
        "timeout_as_missing": True,
        "outlier_filter": "mad",
        "delete_generated_inputs": True,
    },
}

FAMILY_BASELINES = {
    "dijkstra": "dijkstra_baseline",
    "sp_via": "sp_via_baseline",
    "vf3": "vf3_baseline",
    "glasgow": "glasgow_baseline",
}

class TrialFailure(RuntimeError):
    pass


def parse_csv_items(raw: str) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def parse_value_list(raw: str) -> list[float]:
    return [float(item) for item in parse_csv_items(raw)]


def solver_variants_by_id() -> dict[str, app_mod.SolverVariant]:
    return {variant.variant_id: variant for variant in app_mod.SOLVER_VARIANTS}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=app_mod.serialize_for_json) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest must be a JSON object: {path}")
    return payload


def merge_preset_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    merged = dict(payload)
    preset = str(merged.get("preset") or "standard").strip().lower() or "standard"
    if preset not in PRESET_DEFAULTS:
        raise ValueError(f"Unsupported preset: {preset}")
    merged["preset"] = preset
    merged.setdefault("schema_version", MANIFEST_SCHEMA_VERSION)
    merged.setdefault("tab_id", "")
    merged.setdefault("input_mode", "independent")
    merged.setdefault("graph_family", "random_density")
    merged.setdefault("selected_variants", [])
    merged.setdefault("selected_datasets", [])
    merged.setdefault("k_mode", "absolute")
    merged.setdefault("prepare_datasets", True)
    for key, value in PRESET_DEFAULTS[preset].items():
        merged.setdefault(key, value)
    return merged


def build_manifest_from_args(args: argparse.Namespace) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "preset": str(args.preset or "standard").strip().lower() or "standard",
        "tab_id": str(args.tab_id or "").strip().lower(),
        "input_mode": str(args.input_mode or "independent").strip().lower() or "independent",
        "graph_family": str(args.graph_family or "random_density").strip().lower() or "random_density",
        "selected_variants": parse_csv_items(args.variants),
        "selected_datasets": parse_csv_items(args.datasets),
        "k_mode": str(args.k_mode or "absolute").strip().lower() or "absolute",
        "prepare_datasets": not bool(args.no_prepare_datasets),
    }
    if args.iterations is not None:
        manifest["iterations"] = int(args.iterations)
    if args.seed is not None:
        manifest["base_seed"] = int(args.seed)
    if args.solver_timeout_seconds is not None:
        manifest["solver_timeout_seconds"] = float(args.solver_timeout_seconds)
    if args.failure_policy:
        manifest["failure_policy"] = str(args.failure_policy).strip().lower()
    if args.outlier_filter:
        manifest["outlier_filter"] = str(args.outlier_filter).strip().lower()
    if args.retry_failed_trials is not None:
        manifest["retry_failed_trials"] = int(args.retry_failed_trials)
    if args.no_delete_generated_inputs:
        manifest["delete_generated_inputs"] = False
    if manifest["input_mode"] == "independent":
        manifest["values"] = {}
        if args.n_values:
            manifest["values"]["n"] = parse_value_list(args.n_values)
        if args.density_values:
            manifest["values"]["density"] = parse_value_list(args.density_values)
        if args.k_values:
            manifest["values"]["k"] = parse_value_list(args.k_values)
    return manifest


def enforce_baselines(tab_id: str, selected_variants: list[str]) -> tuple[list[str], list[str]]:
    by_id = solver_variants_by_id()
    normalized: list[str] = []
    seen: set[str] = set()
    missing: list[str] = []
    for raw_variant in selected_variants:
        variant_id = str(raw_variant).strip().lower()
        item = by_id.get(variant_id)
        if item is None or item.tab_id != tab_id:
            missing.append(str(raw_variant))
            continue
        if item.variant_id in seen:
            continue
        normalized.append(item.variant_id)
        seen.add(item.variant_id)
    if missing:
        raise ValueError("Unknown or tab-mismatched variants: " + ", ".join(missing))
    injected: list[str] = []
    for variant_id in list(normalized):
        family = app_mod.variant_family_from_id(variant_id)
        baseline_variant = FAMILY_BASELINES.get(family)
        if not baseline_variant or baseline_variant in seen:
            continue
        baseline = by_id.get(baseline_variant)
        if baseline is None or baseline.tab_id != tab_id:
            raise ValueError(f"Missing baseline for family '{family}'")
        normalized.append(baseline_variant)
        seen.add(baseline_variant)
        injected.append(baseline_variant)
    return normalized, injected


def validate_binaries(selected_variants: list[str]) -> None:
    binary_paths = app_mod.build_binary_path_map()
    missing = [f"{variant_id} -> {binary_paths.get(variant_id)}" for variant_id in selected_variants if not binary_paths.get(variant_id) or not binary_paths[variant_id].exists()]
    if missing:
        raise FileNotFoundError("Missing solver binaries:\n" + "\n".join(missing))

def build_independent_config(tab_id: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[float]], dict[str, float], str, str | None]:
    values = dict(payload.get("values") or {})
    n_values = [float(int(round(v))) for v in list(values.get("n") or [])] or ([64.0] if tab_id == "subgraph" else [100.0])
    density_values = [float(v) for v in list(values.get("density") or [])] or [0.05]
    built: dict[str, list[float]] = {"n": n_values, "density": density_values}
    if tab_id == "subgraph":
        built["k"] = [float(v) for v in list(values.get("k") or [])] or [10.0]
    varying = [key for key in (["n", "density"] if tab_id == "shortest_path" else ["n", "density", "k"]) if len(built.get(key) or []) > 1]
    primary_var = varying[0] if varying else "n"
    secondary_var = varying[1] if len(varying) > 1 else None
    var_ranges = {key: sorted({float(v) for v in items}) for key, items in built.items()}
    fixed_values = {key: float(items[0]) for key, items in built.items() if len(items) == 1}
    datapoints: list[dict[str, Any]] = []
    if tab_id == "shortest_path":
        for density in var_ranges["density"]:
            for n_value in var_ranges["n"]:
                datapoints.append({"n": float(n_value), "density": float(density)})
    else:
        k_mode = str(payload.get("k_mode") or "absolute").strip().lower()
        for density in var_ranges["density"]:
            for n_value in var_ranges["n"]:
                n_nodes = int(round(n_value))
                if n_nodes < 3:
                    raise ValueError("Subgraph runs require N >= 3")
                for raw_k in var_ranges["k"]:
                    if k_mode == "percent":
                        if raw_k <= 0.0 or raw_k > 100.0:
                            raise ValueError("k percentage must be in (0, 100]")
                        k_nodes = int(round((raw_k / 100.0) * n_nodes))
                        k_nodes = max(2, min(n_nodes - 1, k_nodes))
                        point_k = float(raw_k)
                    else:
                        k_nodes = int(round(raw_k))
                        if k_nodes < 2 or k_nodes >= n_nodes:
                            raise ValueError("Absolute k must satisfy 2 <= k < N")
                        point_k = float(k_nodes)
                    datapoints.append({"n": float(n_nodes), "density": float(density), "k": point_k, "k_nodes": int(k_nodes)})
    return datapoints, var_ranges, fixed_values, primary_var, secondary_var


def build_dataset_config(tab_id: str, payload: dict[str, Any], logger) -> tuple[list[dict[str, Any]], dict[str, list[float]], dict[str, float], str, str | None, list[dict[str, Any]]]:
    catalog = {spec.dataset_id: spec for spec in app_mod.load_dataset_catalog()}
    selected_specs: list[app_mod.DatasetSpec] = []
    for raw_id in list(payload.get("selected_datasets") or []):
        dataset_id = str(raw_id).strip().lower()
        spec = catalog.get(dataset_id)
        if spec is None or spec.tab_id != tab_id:
            raise ValueError(f"Unknown or tab-mismatched dataset: {raw_id}")
        selected_specs.append(spec)
    if not selected_specs:
        raise ValueError("Select at least one dataset")
    datapoints: list[dict[str, Any]] = []
    observed_n: list[float] = []
    observed_density: list[float] = []
    observed_k: list[float] = []
    dataset_selection: list[dict[str, Any]] = []
    for spec in selected_specs:
        if payload.get("prepare_datasets", True) or not app_mod.dataset_converted_ready(spec):
            logger(f"Preparing dataset {spec.dataset_id} ({spec.name})")
            app_mod.prepare_dataset(spec)
        inputs = app_mod.dataset_converted_inputs(spec)
        if not isinstance(inputs, dict):
            raise RuntimeError(f"Converted inputs missing for dataset {spec.dataset_id}")
        meta = app_mod.read_dataset_meta(app_mod.dataset_dir_for_spec(spec))
        dataset_selection.append({
            "schema_version": DATASET_INFO_SCHEMA_VERSION,
            "dataset_id": spec.dataset_id,
            "dataset_name": spec.name,
            "selected_source_kind": meta.get("source_kind"),
            "selected_archive": meta.get("selected_archive"),
            "selected_pair": meta.get("selected_pair"),
            "selected_instance": meta.get("selected_instance"),
        })
        if tab_id == "subgraph":
            n_nodes = int(meta.get("target_nodes") or 0)
            k_nodes = int(meta.get("pattern_nodes") or 0)
            target_edges = int(meta.get("target_edges") or 0)
            if n_nodes <= 0:
                target_adj = app_mod.parse_vf_graph(Path(inputs["vf_target"]))
                n_nodes = len(target_adj)
                target_edges = app_mod.count_adj_edges(target_adj)
            if k_nodes <= 0:
                pattern_adj = app_mod.parse_vf_graph(Path(inputs["vf_pattern"]))
                k_nodes = len(pattern_adj)
            density = min(1.0, float(target_edges) / float(n_nodes * (n_nodes - 1))) if n_nodes > 1 else 0.0
            k_value = float(k_nodes) if str(payload.get("k_mode") or "absolute").strip().lower() == "absolute" else float((100.0 * k_nodes) / float(n_nodes))
            point = {
                "n": float(n_nodes),
                "density": float(max(0.000001, density)),
                "k": float(k_value),
                "k_nodes": int(k_nodes),
                "dataset_id": spec.dataset_id,
                "dataset_name": spec.name,
                "dataset_inputs": {key: str(value) for key, value in inputs.items()},
            }
            observed_k.append(float(point["k"]))
        else:
            point = {
                "n": float(meta.get("nodes") or 0),
                "density": float(max(0.000001, min(1.0, float(meta.get("density") or 0.0)))),
                "dataset_id": spec.dataset_id,
                "dataset_name": spec.name,
                "dataset_inputs": {key: str(value) for key, value in inputs.items()},
            }
        datapoints.append(point)
        observed_n.append(float(point["n"]))
        observed_density.append(float(point["density"]))
    var_ranges = {"n": sorted({float(v) for v in observed_n}), "density": sorted({float(v) for v in observed_density})}
    fixed_values = {"n": float(datapoints[0]["n"]), "density": float(datapoints[0]["density"])}
    if tab_id == "subgraph":
        var_ranges["k"] = sorted({float(v) for v in observed_k})
        fixed_values["k"] = float(datapoints[0]["k"])
    return datapoints, var_ranges, fixed_values, "n", None, dataset_selection


def build_runtime_config(payload: dict[str, Any], logger) -> dict[str, Any]:
    merged = merge_preset_defaults(payload)
    tab_id = str(merged.get("tab_id") or "").strip().lower()
    if tab_id not in {"subgraph", "shortest_path"}:
        raise ValueError("Manifest requires tab_id=subgraph or tab_id=shortest_path")
    selected_variants, injected_baselines = enforce_baselines(tab_id, [str(item).strip().lower() for item in list(merged.get("selected_variants") or []) if str(item).strip()])
    validate_binaries(selected_variants)
    seed_value = merged.get("base_seed")
    if seed_value is None:
        seed_value = random.SystemRandom().randint(1, 2_147_483_647)
    config: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "preset": merged.get("preset"),
        "tab_id": tab_id,
        "input_mode": str(merged.get("input_mode") or "independent").strip().lower(),
        "graph_family": generator_mod.normalize_graph_family(str(merged.get("graph_family") or "random_density")),
        "selected_variants_requested": list(merged.get("selected_variants") or []),
        "selected_variants": selected_variants,
        "selected_variant_labels": {variant_id: solver_variants_by_id()[variant_id].label for variant_id in selected_variants},
        "injected_baselines": injected_baselines,
        "selected_datasets": list(merged.get("selected_datasets") or []),
        "iterations": int(max(1, int(merged.get("iterations") or 1))),
        "base_seed": int(seed_value),
        "solver_timeout_seconds": None if merged.get("solver_timeout_seconds") in {None, ""} else float(merged.get("solver_timeout_seconds")),
        "failure_policy": str(merged.get("failure_policy") or "continue").strip().lower(),
        "retry_failed_trials": int(max(0, int(merged.get("retry_failed_trials") or 0))),
        "timeout_as_missing": bool(merged.get("timeout_as_missing", True)),
        "outlier_filter": str(merged.get("outlier_filter") or "none").strip().lower(),
        "k_mode": str(merged.get("k_mode") or "absolute").strip().lower() or "absolute",
        "delete_generated_inputs": bool(merged.get("delete_generated_inputs", True)),
        "dataset_selection": [],
    }
    if config["input_mode"] == "datasets":
        datapoints, var_ranges, fixed_values, primary_var, secondary_var, dataset_selection = build_dataset_config(tab_id, merged, logger)
        config["dataset_selection"] = dataset_selection
    else:
        datapoints, var_ranges, fixed_values, primary_var, secondary_var = build_independent_config(tab_id, merged)
    config["datapoints"] = datapoints
    config["var_ranges"] = var_ranges
    config["fixed_values"] = fixed_values
    config["primary_var"] = primary_var
    config["secondary_var"] = secondary_var
    return config

class Runner:
    def __init__(self, output_dir: Path | None = None, logger=None):
        self.binary_paths = app_mod.build_binary_path_map()
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.active_proc_lock = threading.Lock()
        self.active_procs: set[Any] = set()
        self.session_output_dir = output_dir
        self._logger = logger if logger is not None else print

    def after(self, _delay_ms: int, callback=None):
        if callback is not None:
            callback()
        return None

    def _append_log_threadsafe(self, text: str, level: str = "info"):
        self._logger(text)

    def _set_live_log_line_threadsafe(self, token: str, text: str, level: str = "notice"):
        return None

    def _clear_live_log_line_threadsafe(self, token: str | None = None):
        return None

    def _set_process_pause_state(self, paused: bool):
        return None

    def _format_hms(self, total_seconds: int) -> str:
        return app_mod.BenchmarkRunnerApp._format_hms(self, total_seconds)

    def run_process(self, command: list[str], cwd: Path, heartbeat_label: str | None, solver_timeout_seconds: float | None):
        return app_mod.BenchmarkRunnerApp._run_process_with_peak_memory(self, command, cwd, heartbeat_label=heartbeat_label, solver_timeout_seconds=solver_timeout_seconds)

    def build_command(self, variant_id: str, inputs: dict[str, Path | str]) -> list[str]:
        binary = self.binary_paths[variant_id]
        family = app_mod.variant_family_from_id(variant_id)
        if family in {"dijkstra", "sp_via"}:
            return [str(binary), str(inputs["dijkstra_file"])]
        if family == "vf3":
            if variant_id == "vf3_baseline":
                return [str(binary), "-u", "-r", "0", str(inputs["vf_pattern"]), str(inputs["vf_target"])]
            return [str(binary), str(inputs["vf_pattern"]), str(inputs["vf_target"])]
        lad_format = str(inputs.get("lad_format") or "lad").strip() or "lad"
        if variant_id == "glasgow_baseline":
            return [str(binary), "--count-solutions", "--format", lad_format, str(inputs["lad_pattern"]), str(inputs["lad_target"])]
        return [str(binary), str(inputs["lad_pattern"]), str(inputs["lad_target"])]

    def run_trial(self, *, tab_id: str, variant_id: str, inputs: dict[str, Path | str], solver_timeout_seconds: float | None, output_dir: Path) -> dict[str, Any]:
        binary = self.binary_paths[variant_id]
        command = self.build_command(variant_id, inputs)
        family = app_mod.variant_family_from_id(variant_id)
        try:
            runtime_ms, peak_kb, return_code, stdout_text, stderr_text = self.run_process(command, binary.parent, variant_id, solver_timeout_seconds)
            timed_out = False
        except app_mod.SolverTimeoutError as exc:
            runtime_ms, peak_kb, return_code, stdout_text, stderr_text, timed_out = float(exc.elapsed_seconds) * 1000.0, None, None, "", str(exc), True
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = output_dir / f"{variant_id}.stdout.txt"
        stderr_path = output_dir / f"{variant_id}.stderr.txt"
        stdout_path.write_text(stdout_text or "", encoding="utf-8")
        stderr_path.write_text(stderr_text or "", encoding="utf-8")
        combined = (stdout_text or "") + ("\n" + stderr_text if stderr_text else "")
        answer_kind = None
        answer_value: int | str | None = None
        answer_signature = None
        solution_count = None
        distance_value = None
        if family in {"vf3", "glasgow"}:
            solution_count = app_mod.parse_solution_count(combined)
            if solution_count is not None:
                answer_kind, answer_value, answer_signature = "solution_count", int(solution_count), ("solution_count", int(solution_count))
        else:
            distance_value = app_mod.parse_dijkstra_distance(combined)
            if distance_value is not None:
                answer_kind, answer_value, answer_signature = "distance", str(distance_value), ("distance", str(distance_value))
        path_tokens = app_mod.extract_path_tokens(combined) if family in {"dijkstra", "sp_via"} else []
        status = "timeout" if timed_out else ("failed" if return_code not in {None, 0} else "ok")
        return {
            "schema_version": TRIAL_SCHEMA_VERSION,
            "status": status,
            "variant_id": variant_id,
            "family": family,
            "command": command,
            "cwd": str(binary.parent),
            "runtime_ms": None if runtime_ms is None else float(runtime_ms),
            "peak_kb": None if peak_kb is None else float(peak_kb),
            "return_code": return_code,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "normalized_result": {
                "answer_kind": answer_kind,
                "answer_value": answer_value,
                "solution_count": None if solution_count is None else int(solution_count),
                "distance": distance_value,
                "path_length": max(0, len(path_tokens) - 1) if path_tokens else None,
            },
            "answer_signature": answer_signature,
        }


def build_shortest_path_input(
    out_dir: Path,
    *,
    family: str,
    n: int,
    density: float,
    seed: int,
    graph_family: str,
) -> dict[str, Path | str]:
    rng = random.Random(seed)
    labels = [f"v{i}" for i in range(n)]
    edges = generator_mod.generate_directed_edges(n, rng, density, graph_family=graph_family)
    via_label = None
    if family == "sp_via":
        via_index = max(0, min(n - 1, n // 2))
        if n > 2 and via_index in {0, n - 1}:
            via_index = 1
        via_label = labels[via_index]
    path = out_dir / ("sp_via_generated.csv" if family == "sp_via" else "dijkstra_generated.csv")
    with path.open("w", newline="", encoding="utf-8") as fh:
        header = f"# start={labels[0]} target={labels[-1]}"
        if via_label:
            header += f" via={via_label}"
        fh.write(header + "\n")
        writer = csv.writer(fh)
        writer.writerow(["source", "target", "weight"])
        for u, v, weight in edges:
            writer.writerow([labels[u], labels[v], weight])
    max_edges = n * (n - 1)
    metadata = {
        "algorithm": family,
        "graph_family": generator_mod.normalize_graph_family(graph_family),
        "n": int(n),
        "k": None,
        "density": float(density),
        "actual_density": 0.0 if max_edges <= 0 else float(len(edges)) / float(max_edges),
        "seed": int(seed),
        "files": [path.as_posix()],
    }
    if via_label:
        metadata["via"] = via_label
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"dijkstra_file": path}


def build_generated_inputs(config: dict[str, Any], point: dict[str, Any], point_dir: Path, iter_seed: int) -> dict[str, Path | str]:
    if config["tab_id"] == "subgraph":
        return app_mod.generate_subgraph_inputs(
            point_dir,
            int(round(point["n"])),
            int(point.get("k_nodes") or round(point.get("k") or 0)),
            float(point["density"]),
            int(iter_seed),
            graph_family=str(config.get("graph_family") or "random_density"),
        )
    families = {app_mod.variant_family_from_id(variant_id) for variant_id in config["selected_variants"]}
    family = "sp_via" if "sp_via" in families else "dijkstra"
    return build_shortest_path_input(
        point_dir,
        family=family,
        n=int(round(point["n"])),
        density=float(point["density"]),
        seed=int(iter_seed),
        graph_family=str(config.get("graph_family") or "random_density"),
    )


def build_point_label(config: dict[str, Any], point: dict[str, Any]) -> str:
    if config["input_mode"] == "datasets":
        return str(point.get("dataset_name") or point.get("dataset_id") or "dataset")
    dummy = Runner()
    primary = config["primary_var"]
    label = f"{primary}={app_mod.BenchmarkRunnerApp._format_point_value(dummy, primary, float(point[primary]), config)}"
    secondary = config["secondary_var"]
    if secondary is not None:
        label += f", {secondary}={app_mod.BenchmarkRunnerApp._format_point_value(dummy, secondary, float(point[secondary]), config)}"
    return label


def aggregate_metric(values: list[Any]) -> float | None:
    samples = [float(value) for value in values if isinstance(value, (int, float))]
    if not samples:
        return None
    return float(app_mod.statistics.median(samples))


def finalize_point(config: dict[str, Any], state: dict[str, Any], stream) -> list[dict[str, Any]]:
    outlier_mode = str(config.get("outlier_filter") or "none").strip().lower()
    rows: list[dict[str, Any]] = []
    for variant_id in config["selected_variants"]:
        runtimes_raw = [float(value) for value in state["samples_runtime"][variant_id]]
        memories_raw = [float(value) for value in state["samples_memory"][variant_id]]
        runtimes = app_mod.filter_outlier_samples(runtimes_raw, outlier_mode)
        memories = app_mod.filter_outlier_samples(memories_raw, outlier_mode)
        answer_rows = list(state["answer_rows"][variant_id])
        row = {
            "variant_id": variant_id,
            "variant_label": config["selected_variant_labels"][variant_id],
            "x_value": float(state["x_value"]),
            "y_value": None if state["y_value"] is None else float(state["y_value"]),
            "point_label": state["point_label"],
            "dataset_id": state.get("dataset_id"),
            "dataset_name": state.get("dataset_name"),
            "outlier_filter_mode": outlier_mode,
            "outlier_filter_min_samples": int(app_mod.DEFAULT_OUTLIER_MIN_SAMPLES),
            "runtime_median_ms": app_mod.median_or_none(runtimes),
            "runtime_stdev_ms": app_mod.safe_stdev(runtimes),
            "runtime_samples_n": len(runtimes),
            "runtime_samples_total_n": len(runtimes_raw),
            "memory_median_kb": app_mod.median_or_none(memories),
            "memory_stdev_kb": app_mod.safe_stdev(memories),
            "memory_samples_n": len(memories),
            "memory_samples_total_n": len(memories_raw),
            "completed_iterations": int(state["completed_iterations"]),
            "requested_iterations": int(config["iterations"]),
            "seeds": list(state["seed_records"][variant_id]),
            "runtime_samples_ms": [float(value) for value in runtimes],
            "runtime_samples_raw_ms": [float(value) for value in runtimes_raw],
            "memory_samples_kb": [float(value) for value in memories],
            "memory_samples_raw_kb": [float(value) for value in memories_raw],
            "answer_kind": next((item.get("answer_kind") for item in answer_rows if item.get("answer_kind")), None),
            "path_length_median": aggregate_metric([item.get("path_length") for item in answer_rows]),
        }
        stream.write(json.dumps(row, default=app_mod.serialize_for_json) + "\n")
        rows.append(row)
    stream.flush()
    return rows


def write_session_json(path: Path, payload: dict[str, Any]) -> None:
    items_without_datapoints = [(key, value) for key, value in payload.items() if key != "datapoints"]
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("{\n")
        for key, value in items_without_datapoints:
            serialized = json.dumps(value, indent=2, default=app_mod.serialize_for_json)
            if "\n" in serialized:
                serialized = serialized.replace("\n", "\n  ")
            fh.write(f"  {json.dumps(key)}: {serialized},\n")
        fh.write('  "datapoints": [')
        first = True
        for row in payload.get("datapoints", []):
            row_json = json.dumps(row, default=app_mod.serialize_for_json)
            if first:
                fh.write("\n")
                first = False
            else:
                fh.write(",\n")
            fh.write(f"    {row_json}")
        fh.write("]\n" if first else "\n  ]\n")
        fh.write("}\n")


def write_session_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "variant_id", "variant_label", "dataset_id", "dataset_name", "x_value", "y_value", "runtime_median_ms", "runtime_stdev_ms", "runtime_samples_n",
            "memory_median_kb", "memory_stdev_kb", "memory_samples_n", "completed_iterations", "requested_iterations", "answer_kind", "path_length_median",
            "runtime_samples_json", "memory_samples_json", "runtime_samples_raw_json", "memory_samples_raw_json", "seeds_json",
        ])
        for row in rows:
            writer.writerow([
                row.get("variant_id"), row.get("variant_label"), row.get("dataset_id") or "", row.get("dataset_name") or "", app_mod.number_or_blank(row.get("x_value")),
                app_mod.number_or_blank(row.get("y_value")) if row.get("y_value") is not None else "", app_mod.number_or_blank(row.get("runtime_median_ms")),
                app_mod.number_or_blank(row.get("runtime_stdev_ms")), row.get("runtime_samples_n"), app_mod.number_or_blank(row.get("memory_median_kb")),
                app_mod.number_or_blank(row.get("memory_stdev_kb")), row.get("memory_samples_n"), row.get("completed_iterations"), row.get("requested_iterations"),
                row.get("answer_kind") or "", app_mod.number_or_blank(row.get("path_length_median")), json.dumps(row.get("runtime_samples_ms", [])),
                json.dumps(row.get("memory_samples_kb", [])), json.dumps(row.get("runtime_samples_raw_ms", [])), json.dumps(row.get("memory_samples_raw_kb", [])), json.dumps(row.get("seeds", [])),
            ])


def execute_manifest(manifest: dict[str, Any], manifest_path: Path | None, output_dir: Path | None, logger) -> Path:
    config = build_runtime_config(manifest, logger)
    runner = Runner(output_dir=output_dir, logger=logger)
    out_dir = output_dir or app_mod.make_session_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "benchmark-manifest.json", config)
    generated_root = out_dir / "generated_inputs"
    outputs_root = out_dir / "trial_outputs"
    generated_root.mkdir(parents=True, exist_ok=True)
    outputs_root.mkdir(parents=True, exist_ok=True)
    datapoints_path = out_dir / "benchmark-datapoints.ndjson"
    trials_path = out_dir / "benchmark-trials.ndjson"
    started_at = dt.datetime.now(dt.timezone.utc)
    datapoint_rows: list[dict[str, Any]] = []
    point_states: dict[int, dict[str, Any]] = {}
    completed_trials = 0
    planned_trials = len(config["datapoints"]) * len(config["selected_variants"]) * int(config["iterations"])
    with datapoints_path.open("w", encoding="utf-8", newline="\n") as datapoint_stream, trials_path.open("w", encoding="utf-8", newline="\n") as trial_stream:
        for point_idx, point in enumerate(config["datapoints"]):
            point_label = build_point_label(config, point)
            state = {
                "point_label": point_label,
                "dataset_id": point.get("dataset_id"),
                "dataset_name": point.get("dataset_name"),
                "x_value": float(point[config["primary_var"]]),
                "y_value": float(point[config["secondary_var"]]) if config["secondary_var"] else None,
                "samples_runtime": {variant_id: [] for variant_id in config["selected_variants"]},
                "samples_memory": {variant_id: [] for variant_id in config["selected_variants"]},
                "seed_records": {variant_id: [] for variant_id in config["selected_variants"]},
                "iter_answer_signatures": {iter_idx: {} for iter_idx in range(config["iterations"])},
                "iter_runtime_ms": {iter_idx: {} for iter_idx in range(config["iterations"])},
                "answer_rows": {variant_id: [] for variant_id in config["selected_variants"]},
                "completed_iterations": 0,
            }
            point_states[point_idx] = state
            logger(f"Datapoint {point_idx + 1}/{len(config['datapoints'])}: {point_label}")
            for iter_idx in range(config["iterations"]):
                iter_seed = int((int(config["base_seed"]) + point_idx + iter_idx) % 2_147_483_647)
                if iter_seed <= 0:
                    iter_seed = point_idx + iter_idx + 1
                if config["input_mode"] == "datasets":
                    inputs = {key: (Path(value) if key != "lad_format" else str(value)) for key, value in dict(point.get("dataset_inputs") or {}).items()}
                    point_dir = None
                else:
                    point_dir = generated_root / f"point_{point_idx + 1:05d}" / f"iter_{iter_idx + 1:03d}"
                    point_dir.mkdir(parents=True, exist_ok=True)
                    inputs = build_generated_inputs(config, point, point_dir, iter_seed)
                all_ok = True
                for variant_id in config["selected_variants"]:
                    trial = None
                    for attempt_idx in range(int(config.get("retry_failed_trials") or 0) + 1):
                        trial = runner.run_trial(tab_id=config["tab_id"], variant_id=variant_id, inputs=inputs, solver_timeout_seconds=config.get("solver_timeout_seconds"), output_dir=outputs_root / f"point_{point_idx + 1:05d}" / f"iter_{iter_idx + 1:03d}" / f"attempt_{attempt_idx + 1:02d}")
                        if trial.get("status") == "ok":
                            break
                    if trial is None:
                        raise TrialFailure(f"No trial result produced for {variant_id}")
                    trial_stream.write(json.dumps({
                        "schema_version": TRIAL_SCHEMA_VERSION,
                        "status": trial.get("status"),
                        "point_index": int(point_idx),
                        "iteration_index": int(iter_idx),
                        "point_label": point_label,
                        "seed": int(iter_seed),
                        "dataset_id": point.get("dataset_id"),
                        "dataset_name": point.get("dataset_name"),
                        "variant_id": trial.get("variant_id"),
                        "family": trial.get("family"),
                        "command": list(trial.get("command") or []),
                        "cwd": trial.get("cwd"),
                        "runtime_ms": trial.get("runtime_ms"),
                        "peak_kb": trial.get("peak_kb"),
                        "return_code": trial.get("return_code"),
                        "stdout_path": trial.get("stdout_path"),
                        "stderr_path": trial.get("stderr_path"),
                        "normalized_result": dict(trial.get("normalized_result") or {}),
                    }, default=app_mod.serialize_for_json) + "\n")
                    trial_stream.flush()
                    completed_trials += 1
                    normalized = dict(trial.get("normalized_result") or {})
                    state["answer_rows"][variant_id].append(
                        {
                            "answer_kind": normalized.get("answer_kind"),
                            "path_length": normalized.get("path_length"),
                        }
                    )
                    state["seed_records"][variant_id].append(int(iter_seed))
                    state["iter_answer_signatures"][iter_idx][variant_id] = trial.get("answer_signature")
                    if isinstance(trial.get("runtime_ms"), (int, float)):
                        state["samples_runtime"][variant_id].append(float(trial["runtime_ms"]))
                        state["iter_runtime_ms"][iter_idx][variant_id] = float(trial["runtime_ms"])
                    if isinstance(trial.get("peak_kb"), (int, float)):
                        state["samples_memory"][variant_id].append(float(trial["peak_kb"]))
                    if trial.get("status") != "ok":
                        all_ok = False
                        if config.get("failure_policy") == "stop":
                            raise TrialFailure(f"{variant_id} returned status={trial.get('status')} for {point_label} iteration {iter_idx + 1}")
                if all_ok:
                    state["completed_iterations"] += 1
                if point_dir is not None and config.get("delete_generated_inputs", True):
                    shutil.rmtree(point_dir, ignore_errors=True)
            datapoint_rows.extend(finalize_point(config, state, datapoint_stream))
    ended_at = dt.datetime.now(dt.timezone.utc)
    payload = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "run_started_utc": started_at.isoformat(),
        "run_ended_utc": ended_at.isoformat(),
        "run_duration_ms": max(0.0, (ended_at - started_at).total_seconds() * 1000.0),
        "completed_trials": int(completed_trials),
        "planned_trials": int(planned_trials),
        "manifest_path": str(manifest_path) if manifest_path else None,
        "datapoints_path": str(datapoints_path),
        "trials_path": str(trials_path),
        "run_config": {
            "preset": config.get("preset"), "tab_id": config["tab_id"], "input_mode": config["input_mode"], "graph_family": str(config.get("graph_family") or "random_density"),
            "selected_variants_requested": list(config.get("selected_variants_requested") or []), "selected_variants": list(config["selected_variants"]),
            "selected_variant_labels": dict(config["selected_variant_labels"]), "injected_baselines": list(config.get("injected_baselines") or []),
            "selected_datasets": list(config.get("selected_datasets") or []), "iterations_per_datapoint": int(config["iterations"]), "seed": int(config["base_seed"]),
            "solver_timeout_seconds": config.get("solver_timeout_seconds"), "failure_policy": config.get("failure_policy"), "retry_failed_trials": config.get("retry_failed_trials"),
            "timeout_as_missing": config.get("timeout_as_missing"), "outlier_filter": config.get("outlier_filter", "none"), "outlier_filter_min_samples": int(app_mod.DEFAULT_OUTLIER_MIN_SAMPLES),
            "k_mode": config.get("k_mode", "absolute"), "primary_variable": config["primary_var"], "secondary_variable": config["secondary_var"],
            "var_ranges": config["var_ranges"], "fixed_values": config["fixed_values"], "delete_generated_inputs": config.get("delete_generated_inputs", True),
        },
        "dataset_selection": list(config.get("dataset_selection") or []),
        "provenance": collect_runtime_provenance(repo_root=Path(__file__).resolve().parents[1]),
        "statistical_tests": app_mod.build_desktop_runtime_statistical_tests(config=config, point_states=point_states, selected_variants=list(config["selected_variants"])),
        "datapoints": datapoint_rows,
    }
    write_session_json(out_dir / "benchmark-session.json", payload)
    write_session_csv(out_dir / "benchmark-session.csv", datapoint_rows)
    return out_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Headless benchmark runner for the desktop benchmark stack.")
    parser.add_argument("--manifest", default="", help="Load a benchmark manifest JSON file.")
    parser.add_argument("--write-manifest", default="", help="Write the resolved manifest/config to this path.")
    parser.add_argument("--run", action="store_true", help="Run the benchmark after resolving the manifest.")
    parser.add_argument("--list-variants", action="store_true", help="List available solver variants.")
    parser.add_argument("--list-datasets", action="store_true", help="List available datasets.")
    parser.add_argument("--preset", default="standard", choices=sorted(PRESET_DEFAULTS), help="Benchmark preset.")
    parser.add_argument("--tab-id", default="", choices=["", "subgraph", "shortest_path"], help="Benchmark tab/family bucket.")
    parser.add_argument("--input-mode", default="independent", choices=["independent", "datasets"], help="Use generated inputs or prepared datasets.")
    parser.add_argument("--graph-family", default="random_density", choices=list(generator_mod.GRAPH_FAMILIES), help="Synthetic graph family for generated runs.")
    parser.add_argument("--variants", default="", help="Comma-separated variant ids.")
    parser.add_argument("--datasets", default="", help="Comma-separated dataset ids.")
    parser.add_argument("--n-values", default="", help="Comma-separated N values for independent runs.")
    parser.add_argument("--density-values", default="", help="Comma-separated density values for independent runs.")
    parser.add_argument("--k-values", default="", help="Comma-separated k values for subgraph runs.")
    parser.add_argument("--k-mode", default="absolute", choices=["absolute", "percent"], help="Interpret k as node count or percentage.")
    parser.add_argument("--iterations", type=int, default=None, help="Override preset iteration count.")
    parser.add_argument("--seed", type=int, default=None, help="Base seed override.")
    parser.add_argument("--solver-timeout-seconds", type=float, default=None, help="Per-trial timeout override.")
    parser.add_argument("--failure-policy", default="", choices=["", "stop", "continue"], help="Stop or continue on failed trials.")
    parser.add_argument("--outlier-filter", default="", choices=["", "none", "mad", "iqr"], help="Outlier filter.")
    parser.add_argument("--retry-failed-trials", type=int, default=None, help="Retry count for failed trials.")
    parser.add_argument("--out-dir", default="", help="Optional benchmark output directory.")
    parser.add_argument("--no-delete-generated-inputs", action="store_true", help="Keep generated input files after the run.")
    parser.add_argument("--no-prepare-datasets", action="store_true", help="Assume selected datasets are already prepared.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_variants:
        for variant in app_mod.SOLVER_VARIANTS:
            print(f"{variant.variant_id}\t{variant.tab_id}\t{variant.family}\t{variant.role}\t{variant.label}")
        return 0
    if args.list_datasets:
        for spec in app_mod.load_dataset_catalog():
            print(f"{spec.dataset_id}\t{spec.tab_id}\t{spec.name}")
        return 0
    manifest_path = Path(args.manifest).resolve() if args.manifest else None
    manifest = load_manifest(manifest_path) if manifest_path is not None else build_manifest_from_args(args)
    manifest = merge_preset_defaults(manifest)
    if args.write_manifest:
        write_json(Path(args.write_manifest).resolve(), manifest)
        print(f"Wrote manifest: {Path(args.write_manifest).resolve()}")
        if not args.run and manifest_path is None:
            return 0
    output_dir = Path(args.out_dir).resolve() if args.out_dir else None
    if not args.run and manifest_path is None:
        print("Resolved manifest. Use --run to execute it.")
        return 0
    out_dir = execute_manifest(manifest, manifest_path, output_dir, print)
    print(f"Benchmark run complete: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
