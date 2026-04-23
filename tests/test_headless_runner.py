import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import json
import sys
import io as stdio

from desktop_runner import app, headless_runner


# - These tests cover shared manifest/building behavior that can regress when
#   desktop and headless execution paths drift apart.
# - Prefer asserting on serialized shapes and injected defaults here because
#   those are the contracts external automation depends on.
class HeadlessRunnerTests(unittest.TestCase):
    def test_enforce_baselines_injects_family_baseline(self):
        selected, injected = headless_runner.enforce_baselines("subgraph", ["vf3_chatgpt_control"])
        self.assertIn("vf3_chatgpt_control", selected)
        self.assertIn("vf3_baseline", selected)
        self.assertEqual(injected, ["vf3_baseline"])

    def test_enforce_baselines_uses_source_discovery_catalog(self):
        baseline_rows = [variant for variant in app.SOLVER_VARIANTS if variant.role == "baseline"]
        with mock.patch.object(app, "SOLVER_VARIANTS", baseline_rows):
            selected, injected = headless_runner.enforce_baselines("subgraph", ["vf3_chatgpt_control"])
        self.assertIn("vf3_chatgpt_control", selected)
        self.assertEqual(injected, ["vf3_baseline"])

    def test_build_runtime_config_generates_subgraph_points(self):
        with mock.patch.object(headless_runner, "resolve_selected_variants", side_effect=lambda selected: (selected, [])):
            config = headless_runner.build_runtime_config(
                {
                    "preset": "smoke",
                    "tab_id": "subgraph",
                    "input_mode": "independent",
                    "graph_family": "erdos_renyi",
                    "selected_variants": ["vf3_chatgpt_control"],
                    "k_mode": "absolute",
                    "values": {"n": [8], "density": [0.2], "k": [3, 4]},
                },
                lambda _msg: None,
            )
        self.assertEqual(config["primary_var"], "k")
        self.assertEqual(len(config["datapoints"]), 2)
        self.assertEqual(config["datapoints"][0]["k_nodes"], 3)
        self.assertEqual(config["graph_family"], "erdos_renyi")
        self.assertIn("vf3_baseline", config["selected_variants"])

    def test_list_collection_manifest_paths_reads_top_level_json_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "01_first.json").write_text("{}\n", encoding="utf-8")
            (root / "02_second.JSON").write_text("{}\n", encoding="utf-8")
            (root / "README.md").write_text("ignore\n", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "03_nested.json").write_text("{}\n", encoding="utf-8")

            paths = headless_runner.list_collection_manifest_paths(root)

        self.assertEqual([path.name for path in paths], ["01_first.json", "02_second.JSON"])

    def test_execute_manifest_collection_writes_invocation_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "01_alpha.json").write_text('{"tab_id":"shortest_path"}\n', encoding="utf-8")
            (root / "02_beta.json").write_text('{"tab_id":"subgraph"}\n', encoding="utf-8")
            calls = []

            def fake_execute(manifest, manifest_path, output_dir, logger):
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "benchmark-session.json").write_text(
                    json.dumps({"manifest_path": str(manifest_path)}) + "\n",
                    encoding="utf-8",
                )
                calls.append((dict(manifest), manifest_path.name, output_dir.name))
                return output_dir

            with mock.patch.object(headless_runner, "execute_manifest", side_effect=fake_execute):
                out_dir, summary = headless_runner.execute_manifest_collection(root, None, lambda _msg: None)

            self.assertEqual(out_dir.parent, root / "runs")
            self.assertEqual([item[1] for item in calls], ["01_alpha.json", "02_beta.json"])
            self.assertTrue((out_dir / "01_alpha" / "input-manifest.json").is_file())
            self.assertTrue((out_dir / "02_beta" / "input-manifest.json").is_file())
            self.assertTrue((out_dir / "collection-run.json").is_file())
            self.assertEqual(summary["collection_label"], "Data Collection")
            self.assertEqual(summary["discovered_manifest_count"], 2)
            self.assertEqual(summary["failed_manifest_count"], 0)
            self.assertEqual([row["status"] for row in summary["runs"]], ["ok", "ok"])

    def test_build_runtime_config_has_no_solver_timeout_by_default(self):
        with mock.patch.object(headless_runner, "resolve_selected_variants", side_effect=lambda selected: (selected, [])):
            config = headless_runner.build_runtime_config(
                {
                    "preset": "full",
                    "tab_id": "shortest_path",
                    "input_mode": "independent",
                    "graph_family": "erdos_renyi",
                    "selected_variants": ["dijkstra_chatgpt"],
                    "values": {"n": [128], "density": [0.01]},
                },
                lambda _msg: None,
            )
        self.assertIsNone(config["solver_timeout_seconds"])

    def test_build_runtime_config_defaults_parallel_workers_to_half_logical_cores(self):
        with mock.patch.object(headless_runner, "detect_logical_cores", return_value=8):
            with mock.patch.object(headless_runner, "resolve_selected_variants", side_effect=lambda selected: (selected, [])):
                config = headless_runner.build_runtime_config(
                    {
                        "preset": "full",
                        "tab_id": "shortest_path",
                        "input_mode": "independent",
                        "graph_family": "erdos_renyi",
                        "selected_variants": ["dijkstra_chatgpt"],
                        "values": {"n": [128], "density": [0.01]},
                    },
                    lambda _msg: None,
                )

        self.assertTrue(config["parallel_requested"])
        self.assertEqual(config["requested_workers"], 4)
        self.assertEqual(config["max_workers"], 4)
        self.assertEqual(config["detected_logical_cores"], 8)

    def test_build_manifest_from_args_accepts_parallel_flags(self):
        parser = headless_runner.build_parser()
        args = parser.parse_args(
            [
                "--tab-id",
                "shortest_path",
                "--variants",
                "dijkstra_chatgpt",
                "--parallel-auto",
                "--max-workers",
                "3",
            ]
        )

        manifest = headless_runner.build_manifest_from_args(args)

        self.assertTrue(manifest["parallel_auto"])
        self.assertEqual(manifest["max_workers"], 3)
        self.assertEqual(manifest["requested_workers"], 3)
        self.assertTrue(manifest["parallel_requested"])

    def test_build_runtime_config_skips_missing_optional_variants(self):
        captured = []
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            baseline = root / "dijkstra_baseline.exe"
            baseline.write_text("ok", encoding="utf-8")
            binary_map = {
                "dijkstra_baseline": baseline,
                "dijkstra_chatgpt": root / "dijkstra_chatgpt.exe",
            }
            with mock.patch.object(app, "build_binary_path_map", return_value=binary_map):
                config = headless_runner.build_runtime_config(
                    {
                        "preset": "smoke",
                        "tab_id": "shortest_path",
                        "input_mode": "independent",
                        "graph_family": "erdos_renyi",
                        "selected_variants": ["dijkstra_chatgpt"],
                        "values": {"n": [128], "density": [0.01]},
                    },
                    lambda msg: captured.append(msg),
                )

        self.assertEqual(config["selected_variants"], ["dijkstra_baseline"])
        self.assertEqual([row["variant_id"] for row in config["skipped_missing_variants"]], ["dijkstra_chatgpt"])
        self.assertTrue(any("Skipping missing optional solver binaries" in line for line in captured))

    def test_run_trial_extracts_shortest_path_length_from_output(self):
        runner = headless_runner.Runner(output_dir=None, logger=lambda _msg: None)
        runner.binary_paths = {"dijkstra_baseline": Path.cwd() / "baselines" / "dijkstra.exe"}

        with mock.patch.object(
            runner,
            "run_process",
            return_value=(12.0, 256.0, 0, "6\nv0->v1->v2->v3\n", ""),
        ):
            trial = runner.run_trial(
                tab_id="shortest_path",
                variant_id="dijkstra_baseline",
                inputs={"dijkstra_file": Path.cwd() / "data" / "dijkstra_sample.csv"},
                solver_timeout_seconds=None,
                output_dir=Path(tempfile.mkdtemp()),
            )

        self.assertEqual(trial["status"], "ok")
        self.assertEqual(trial["normalized_result"]["distance"], "6")
        self.assertEqual(trial["normalized_result"]["path_length"], 3)

    def test_runner_live_log_overwrites_console_line(self):
        captured = []
        runner = headless_runner.Runner(output_dir=None, logger=lambda text: captured.append(text))
        runner._console_stream = stdio.StringIO()
        runner._supports_inplace_live_line = True

        runner._set_live_log_line_threadsafe("hb", "Update: still running", level="notice")
        runner._append_log_threadsafe("Datapoint complete", level="info")

        console_output = runner._console_stream.getvalue()
        self.assertIn("\rUpdate: still running", console_output)
        self.assertIn("\r", console_output)
        self.assertEqual(captured, ["Datapoint complete"])

    def test_execute_manifest_uses_configured_parallel_worker_count(self):
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            captured = {"max_workers": None, "submit_count": 0}

            class FakeExecutor:
                def __init__(self, *, max_workers: int, thread_name_prefix: str):
                    captured["max_workers"] = max_workers

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def submit(self, fn, *args, **kwargs):
                    captured["submit_count"] += 1
                    future = headless_runner.concurrent.futures.Future()
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except Exception as exc:
                        future.set_exception(exc)
                    return future

            config = {
                "preset": "smoke",
                "tab_id": "shortest_path",
                "input_mode": "independent",
                "graph_family": "erdos_renyi",
                "selected_variants_requested": ["dijkstra_baseline", "dijkstra_chatgpt"],
                "selected_variants": ["dijkstra_baseline", "dijkstra_chatgpt"],
                "selected_variant_labels": {
                    "dijkstra_baseline": "Dijkstra Baseline",
                    "dijkstra_chatgpt": "Dijkstra Chatgpt",
                },
                "injected_baselines": [],
                "skipped_missing_variants": [],
                "selected_datasets": [],
                "iterations": 1,
                "base_seed": 11,
                "solver_timeout_seconds": None,
                "failure_policy": "continue",
                "retry_failed_trials": 0,
                "timeout_as_missing": True,
                "outlier_filter": "none",
                "k_mode": "absolute",
                "delete_generated_inputs": True,
                "dataset_selection": [],
                "parallel_requested": True,
                "requested_workers": 2,
                "max_workers": 2,
                "detected_logical_cores": 4,
                "datapoints": [{"n": 8.0, "density": 0.2}],
                "var_ranges": {"n": [8.0], "density": [0.2]},
                "fixed_values": {"n": 8.0, "density": 0.2},
                "primary_var": "n",
                "secondary_var": None,
            }

            trial_counter = {"value": 0}

            def fake_run_trial(**kwargs):
                trial_counter["value"] += 1
                variant_id = kwargs["variant_id"]
                output_dir = kwargs["output_dir"]
                output_dir.mkdir(parents=True, exist_ok=True)
                stdout_path = output_dir / f"{variant_id}.stdout.txt"
                stderr_path = output_dir / f"{variant_id}.stderr.txt"
                stdout_path.write_text("ok\n", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                return {
                    "schema_version": headless_runner.TRIAL_SCHEMA_VERSION,
                    "status": "ok",
                    "variant_id": variant_id,
                    "family": "dijkstra",
                    "command": [variant_id],
                    "cwd": str(output_dir),
                    "runtime_ms": 10.0 + trial_counter["value"],
                    "peak_kb": 128.0,
                    "return_code": 0,
                    "stdout_path": stdout_path,
                    "stderr_path": stderr_path,
                    "normalized_result": {
                        "answer_kind": "distance",
                        "answer_value": "7",
                        "solution_count": None,
                        "distance": "7",
                        "path_length": 2,
                    },
                    "answer_signature": ("distance", "7"),
                }

            with mock.patch.object(headless_runner, "build_runtime_config", return_value=config):
                with mock.patch.object(headless_runner, "build_generated_inputs", return_value={"dijkstra_file": Path(td) / "generated.csv"}):
                    with mock.patch.object(headless_runner.Runner, "run_trial", side_effect=fake_run_trial):
                        with mock.patch.object(headless_runner.concurrent.futures, "ThreadPoolExecutor", FakeExecutor):
                            final_out_dir = headless_runner.execute_manifest({}, None, out_dir, lambda _msg: None)

        self.assertEqual(final_out_dir, out_dir)
        self.assertEqual(captured["max_workers"], 2)
        self.assertEqual(captured["submit_count"], 2)

    def test_save_session_plot_exports_writes_runtime_and_memory_pngs(self):
        payload = {
            "completed_trials": 3,
            "planned_trials": 3,
            "run_duration_ms": 1234.0,
            "run_config": {
                "tab_id": "shortest_path",
                "input_mode": "independent",
                "graph_family": "erdos_renyi",
                "selected_variants": ["dijkstra_baseline", "dijkstra_chatgpt"],
                "selected_variant_labels": {
                    "dijkstra_baseline": "Dijkstra Baseline",
                    "dijkstra_chatgpt": "Dijkstra Chatgpt",
                },
                "selected_datasets": [],
                "iterations_per_datapoint": 3,
                "seed": 11,
                "solver_timeout_seconds": 120.0,
                "failure_policy": "continue",
                "outlier_filter": "mad",
                "injected_baselines": ["dijkstra_baseline"],
                "k_mode": "absolute",
                "primary_variable": "n",
                "secondary_variable": None,
                "var_ranges": {"n": [128.0, 256.0], "density": [0.01]},
                "fixed_values": {"density": 0.01},
            },
            "dataset_selection": [],
            "datapoints": [
                {
                    "variant_id": "dijkstra_baseline",
                    "variant_label": "Dijkstra Baseline",
                    "x_value": 128.0,
                    "y_value": None,
                    "runtime_median_ms": 10.0,
                    "runtime_stdev_ms": 1.0,
                    "memory_median_kb": 100.0,
                    "memory_stdev_kb": 5.0,
                },
                {
                    "variant_id": "dijkstra_baseline",
                    "variant_label": "Dijkstra Baseline",
                    "x_value": 256.0,
                    "y_value": None,
                    "runtime_median_ms": 20.0,
                    "runtime_stdev_ms": 1.5,
                    "memory_median_kb": 150.0,
                    "memory_stdev_kb": 7.0,
                },
                {
                    "variant_id": "dijkstra_chatgpt",
                    "variant_label": "Dijkstra Chatgpt",
                    "x_value": 128.0,
                    "y_value": None,
                    "runtime_median_ms": 12.0,
                    "runtime_stdev_ms": 1.2,
                    "memory_median_kb": 110.0,
                    "memory_stdev_kb": 4.0,
                },
                {
                    "variant_id": "dijkstra_chatgpt",
                    "variant_label": "Dijkstra Chatgpt",
                    "x_value": 256.0,
                    "y_value": None,
                    "runtime_median_ms": 24.0,
                    "runtime_stdev_ms": 1.8,
                    "memory_median_kb": 170.0,
                    "memory_stdev_kb": 6.0,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            app.save_session_plot_exports(payload, out_dir)
            runtime_png = out_dir / "runtime-2d.png"
            memory_png = out_dir / "memory-2d.png"
            runtime_svg = out_dir / "runtime-2d.svg"
            memory_svg = out_dir / "memory-2d.svg"
            self.assertTrue(runtime_png.is_file())
            self.assertTrue(memory_png.is_file())
            self.assertTrue(runtime_svg.is_file())
            self.assertTrue(memory_svg.is_file())
            self.assertEqual(runtime_png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(memory_png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertIn("<svg", runtime_svg.read_text(encoding="utf-8"))
            self.assertIn("<svg", memory_svg.read_text(encoding="utf-8"))

    def test_save_session_plot_exports_writes_subgraph_family_pngs(self):
        payload = {
            "completed_trials": 4,
            "planned_trials": 4,
            "run_duration_ms": 2500.0,
            "run_config": {
                "tab_id": "subgraph",
                "input_mode": "independent",
                "graph_family": "erdos_renyi",
                "selected_variants": ["vf3_baseline", "vf3_chatgpt_control", "glasgow_baseline", "glasgow_chatgpt_control"],
                "selected_variant_labels": {
                    "vf3_baseline": "VF3 Baseline",
                    "vf3_chatgpt_control": "VF3 Chatgpt Control",
                    "glasgow_baseline": "Glasgow Baseline",
                    "glasgow_chatgpt_control": "Glasgow Chatgpt Control",
                },
                "selected_datasets": [],
                "iterations_per_datapoint": 2,
                "seed": 29,
                "solver_timeout_seconds": 180.0,
                "failure_policy": "continue",
                "outlier_filter": "mad",
                "injected_baselines": ["vf3_baseline", "glasgow_baseline"],
                "k_mode": "percent",
                "primary_variable": "n",
                "secondary_variable": None,
                "var_ranges": {"n": [32.0, 64.0], "density": [0.05], "k": [20.0]},
                "fixed_values": {"density": 0.05, "k": 20.0},
            },
            "dataset_selection": [],
            "datapoints": [
                {
                    "variant_id": "vf3_baseline",
                    "variant_label": "VF3 Baseline",
                    "x_value": 32.0,
                    "y_value": None,
                    "runtime_median_ms": 5.0,
                    "runtime_stdev_ms": 0.4,
                    "memory_median_kb": 90.0,
                    "memory_stdev_kb": 4.0,
                },
                {
                    "variant_id": "vf3_chatgpt_control",
                    "variant_label": "VF3 Chatgpt Control",
                    "x_value": 32.0,
                    "y_value": None,
                    "runtime_median_ms": 6.0,
                    "runtime_stdev_ms": 0.5,
                    "memory_median_kb": 96.0,
                    "memory_stdev_kb": 4.5,
                },
                {
                    "variant_id": "glasgow_baseline",
                    "variant_label": "Glasgow Baseline",
                    "x_value": 32.0,
                    "y_value": None,
                    "runtime_median_ms": 7.0,
                    "runtime_stdev_ms": 0.6,
                    "memory_median_kb": 110.0,
                    "memory_stdev_kb": 5.0,
                },
                {
                    "variant_id": "glasgow_chatgpt_control",
                    "variant_label": "Glasgow Chatgpt Control",
                    "x_value": 32.0,
                    "y_value": None,
                    "runtime_median_ms": 8.0,
                    "runtime_stdev_ms": 0.7,
                    "memory_median_kb": 118.0,
                    "memory_stdev_kb": 5.5,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            app.save_session_plot_exports(payload, out_dir)
            expected = [
                "runtime-2d.png",
                "runtime-2d.svg",
                "memory-2d.png",
                "memory-2d.svg",
                "runtime-2d-both.png",
                "runtime-2d-both.svg",
                "memory-2d-both.png",
                "memory-2d-both.svg",
                "runtime-2d-vf3.png",
                "runtime-2d-vf3.svg",
                "memory-2d-vf3.png",
                "memory-2d-vf3.svg",
                "runtime-2d-glasgow.png",
                "runtime-2d-glasgow.svg",
                "memory-2d-glasgow.png",
                "memory-2d-glasgow.svg",
            ]
            for name in expected:
                path = out_dir / name
                self.assertTrue(path.is_file(), name)
                if path.suffix.lower() == ".png":
                    self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                else:
                    self.assertIn("<svg", path.read_text(encoding="utf-8"))

    def test_save_session_plot_exports_reads_streamed_datapoints_path(self):
        payload = {
            "completed_trials": 4,
            "planned_trials": 4,
            "run_duration_ms": 2500.0,
            "run_config": {
                "tab_id": "subgraph",
                "input_mode": "independent",
                "graph_family": "erdos_renyi",
                "selected_variants": ["vf3_baseline", "glasgow_baseline"],
                "selected_variant_labels": {
                    "vf3_baseline": "VF3 Baseline",
                    "glasgow_baseline": "Glasgow Baseline",
                },
                "selected_datasets": [],
                "iterations_per_datapoint": 2,
                "seed": 29,
                "solver_timeout_seconds": 180.0,
                "failure_policy": "continue",
                "outlier_filter": "mad",
                "injected_baselines": ["vf3_baseline", "glasgow_baseline"],
                "k_mode": "percent",
                "primary_variable": "n",
                "secondary_variable": None,
                "var_ranges": {"n": [32.0, 64.0], "density": [0.05], "k": [20.0]},
                "fixed_values": {"density": 0.05, "k": 20.0},
            },
            "dataset_selection": [],
            "datapoints": [],
        }
        streamed_rows = [
            {
                "variant_id": "vf3_baseline",
                "variant_label": "VF3 Baseline",
                "x_value": 32.0,
                "y_value": None,
                "runtime_median_ms": 5.0,
                "runtime_stdev_ms": 0.4,
                "memory_median_kb": 90.0,
                "memory_stdev_kb": 4.0,
            },
            {
                "variant_id": "vf3_baseline",
                "variant_label": "VF3 Baseline",
                "x_value": 64.0,
                "y_value": None,
                "runtime_median_ms": 7.0,
                "runtime_stdev_ms": 0.5,
                "memory_median_kb": 110.0,
                "memory_stdev_kb": 5.0,
            },
            {
                "variant_id": "glasgow_baseline",
                "variant_label": "Glasgow Baseline",
                "x_value": 32.0,
                "y_value": None,
                "runtime_median_ms": 6.0,
                "runtime_stdev_ms": 0.4,
                "memory_median_kb": 95.0,
                "memory_stdev_kb": 4.5,
            },
            {
                "variant_id": "glasgow_baseline",
                "variant_label": "Glasgow Baseline",
                "x_value": 64.0,
                "y_value": None,
                "runtime_median_ms": 8.0,
                "runtime_stdev_ms": 0.6,
                "memory_median_kb": 120.0,
                "memory_stdev_kb": 5.5,
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            datapoints_path = out_dir / "benchmark-datapoints.ndjson"
            datapoints_path.write_text(
                "\n".join(json.dumps(row) for row in streamed_rows) + "\n",
                encoding="utf-8",
            )
            payload["datapoints_path"] = str(datapoints_path)
            app.save_session_plot_exports(payload, out_dir)
            for name in [
                "runtime-2d.png",
                "memory-2d.png",
                "runtime-2d.svg",
                "memory-2d.svg",
                "runtime-2d-both.png",
                "memory-2d-both.png",
                "runtime-2d-vf3.png",
                "memory-2d-vf3.png",
                "runtime-2d-glasgow.png",
                "memory-2d-glasgow.png",
            ]:
                path = out_dir / name
                self.assertTrue(path.is_file(), name)

    def test_try_save_figure_writes_png(self):
        fig = app.build_metric_summary_figure(
            {
                "completed_trials": 1,
                "planned_trials": 1,
                "run_duration_ms": 1000.0,
                "run_config": {
                    "tab_id": "shortest_path",
                    "input_mode": "independent",
                    "graph_family": "erdos_renyi",
                    "selected_variants": ["dijkstra_baseline"],
                    "selected_variant_labels": {
                        "dijkstra_baseline": "Dijkstra Baseline",
                    },
                    "selected_datasets": [],
                    "iterations_per_datapoint": 1,
                    "seed": 7,
                    "solver_timeout_seconds": None,
                    "failure_policy": "continue",
                    "outlier_filter": "none",
                    "injected_baselines": [],
                    "primary_variable": "n",
                    "secondary_variable": None,
                    "var_ranges": {"n": [16.0, 32.0], "density": [0.1]},
                    "fixed_values": {"density": 0.1},
                },
                "dataset_selection": [],
                "datapoints": [
                    {
                        "variant_id": "dijkstra_baseline",
                        "variant_label": "Dijkstra Baseline",
                        "x_value": 16.0,
                        "y_value": None,
                        "runtime_median_ms": 5.0,
                        "runtime_stdev_ms": 0.2,
                        "memory_median_kb": 100.0,
                        "memory_stdev_kb": 3.0,
                    },
                    {
                        "variant_id": "dijkstra_baseline",
                        "variant_label": "Dijkstra Baseline",
                        "x_value": 32.0,
                        "y_value": None,
                        "runtime_median_ms": 7.0,
                        "runtime_stdev_ms": 0.3,
                        "memory_median_kb": 110.0,
                        "memory_stdev_kb": 4.0,
                    },
                ],
            },
            "runtime",
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runtime.png"
            saved, error_text = app.try_save_figure(fig, path, dpi=150)
            self.assertTrue(saved)
            self.assertIsNone(error_text)
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_try_save_figure_skips_empty_figure(self):
        fig = app.Figure(figsize=(4.0, 3.0), dpi=100)
        fig.add_subplot(111)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.png"
            saved, error_text = app.try_save_figure(fig, path, dpi=150)
        self.assertFalse(saved)
        self.assertEqual(error_text, "no plotted data")

    def test_try_save_figure_returns_error_text(self):
        fig = app.build_metric_summary_figure(
            {
                "completed_trials": 1,
                "planned_trials": 1,
                "run_duration_ms": 1000.0,
                "run_config": {
                    "tab_id": "shortest_path",
                    "input_mode": "independent",
                    "graph_family": "erdos_renyi",
                    "selected_variants": ["dijkstra_baseline"],
                    "selected_variant_labels": {
                        "dijkstra_baseline": "Dijkstra Baseline",
                    },
                    "selected_datasets": [],
                    "iterations_per_datapoint": 1,
                    "seed": 7,
                    "solver_timeout_seconds": None,
                    "failure_policy": "continue",
                    "outlier_filter": "none",
                    "injected_baselines": [],
                    "primary_variable": "n",
                    "secondary_variable": None,
                    "var_ranges": {"n": [16.0, 32.0], "density": [0.1]},
                    "fixed_values": {"density": 0.1},
                },
                "dataset_selection": [],
                "datapoints": [
                    {
                        "variant_id": "dijkstra_baseline",
                        "variant_label": "Dijkstra Baseline",
                        "x_value": 16.0,
                        "y_value": None,
                        "runtime_median_ms": 5.0,
                        "runtime_stdev_ms": 0.2,
                        "memory_median_kb": 100.0,
                        "memory_stdev_kb": 3.0,
                    },
                    {
                        "variant_id": "dijkstra_baseline",
                        "variant_label": "Dijkstra Baseline",
                        "x_value": 32.0,
                        "y_value": None,
                        "runtime_median_ms": 7.0,
                        "runtime_stdev_ms": 0.3,
                        "memory_median_kb": 110.0,
                        "memory_stdev_kb": 4.0,
                    },
                ],
            },
            "runtime",
        )
        fig.savefig = mock.Mock(side_effect=ModuleNotFoundError("No module named 'matplotlib.backends.backend_svg'"))
        with tempfile.TemporaryDirectory() as td:
            saved, error_text = app.try_save_figure(fig, Path(td) / "runtime.svg")
        self.assertFalse(saved)
        self.assertIn("backend_svg", error_text or "")


class DatasetConversionTests(unittest.TestCase):
    @staticmethod
    def _mivia_unlabelled_graph(adj):
        words = [len(adj)]
        for row in adj:
            words.append(len(row))
            words.extend(int(v) for v in row)
        return b"".join(int(word).to_bytes(2, "little", signed=False) for word in words)

    def test_select_mivia_pair_reads_nested_archive(self):
        with tempfile.TemporaryDirectory() as td:
            outer_path = Path(td) / "graphsdb.zip"
            inner_buffer = io.BytesIO()
            with zipfile.ZipFile(inner_buffer, "w") as inner_zip:
                inner_zip.writestr("demo.A01", self._mivia_unlabelled_graph([[1], [0]]))
                inner_zip.writestr("demo.B01", self._mivia_unlabelled_graph([[1], [0, 2], [1]]))
            with zipfile.ZipFile(outer_path, "w") as outer_zip:
                outer_zip.writestr("si2_demo.zip", inner_buffer.getvalue())
                outer_zip.writestr("si2_demo.gtr", "demo.A01 1\n")
            pattern_adj, target_adj, pattern_labels, target_labels, meta = app._select_mivia_pair(
                outer_path,
                {"inner_zip_prefix": "si2_", "labeled": False},
            )
        self.assertEqual(pattern_adj, [[1], [0]])
        self.assertEqual(target_adj, [[1], [0, 2], [1]])
        self.assertIsNone(pattern_labels)
        self.assertIsNone(target_labels)
        self.assertEqual(meta["selected_archive"], "si2_demo.zip")

    def test_parse_bigraph_instance_emits_structure_and_labels(self):
        text = """{(0, Child:1),(1, Locale:1),(2, Lion:1),(3, Impala:1)}
2 4 1
10000
01000
00000
00111
00000
00000
({}, {n0}, {(0, 1), (2, 1)})
({}, {n1}, {(3, 1)})
({}, {n2}, {(1, 1)})
"""
        adj, labels = app._parse_bigraph_instance(text)
        self.assertGreaterEqual(len(adj), 8)
        self.assertEqual(labels[0], "__root__")
        self.assertIn("Child", labels)
        self.assertIn("__handle__", labels)


class DesktopHeadlessForwardingTests(unittest.TestCase):
    def test_app_main_forwards_manifest_dir_runs_to_headless_cli(self):
        with tempfile.TemporaryDirectory() as td:
            argv = ["app.py", "--manifest-dir", td, "--run"]
            with mock.patch("desktop_runner.headless_runner.main", return_value=0) as mocked_headless:
                with mock.patch.object(sys, "argv", argv):
                    rc = app.main()
        self.assertEqual(rc, 0)
        mocked_headless.assert_called_once_with(["--manifest-dir", td, "--run"])

    def test_app_main_forwards_help_to_headless_cli_when_requested(self):
        argv = ["app.py", "--headless", "--help"]
        with mock.patch("desktop_runner.headless_runner.main", return_value=0) as mocked_headless:
            with mock.patch.object(sys, "argv", argv):
                rc = app.main()
        self.assertEqual(rc, 0)
        mocked_headless.assert_called_once_with(["--help"])


if __name__ == "__main__":
    unittest.main()
