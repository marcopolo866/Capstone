import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CREATE_RESULT_SCRIPT = REPO_ROOT / ".github" / "scripts" / "create-result-json-step.py"


class CreateResultJsonStepTests(unittest.TestCase):
    def run_create_result(self, *, workdir: Path, env_overrides: dict[str, str]):
        env = os.environ.copy()
        env.update(env_overrides)
        subprocess.run([sys.executable, str(CREATE_RESULT_SCRIPT)], cwd=workdir, env=env, check=True)
        return json.loads((workdir / "outputs" / "result.json").read_text(encoding="utf-8"))

    def test_prefers_structured_metrics_json_when_present(self):
        with tempfile.TemporaryDirectory(prefix="capstone-test-result-json-") as tmp:
            workdir = Path(tmp)
            outputs = workdir / "outputs"
            outputs.mkdir(parents=True, exist_ok=True)
            (outputs / "result.txt").write_text("benchmark output\n", encoding="utf-8")

            metrics_path = outputs / "run_metrics.json"
            metrics = {
                "ALGORITHM_INPUT": "dijkstra",
                "EXIT_CODE": "0",
                "REQUEST_ID_INPUT": "req-structured",
                "INPUT_MODE_INPUT": "generate",
                "GENERATOR_N_INPUT": "50",
                "GENERATOR_GRAPH_FAMILY_INPUT": "barabasi_albert",
                "GENERATOR_DENSITY_INPUT": "0.12",
                "SEED_USED": "98765",
                "ITERATIONS": "5",
                "WARMUP": "1",
                "RUN_DURATION_MS": "321.5",
                "DIJKSTRA_BASELINE_MS": "10.25",
                "DIJKSTRA_LLM_MS": "11.5",
                "DIJKSTRA_GEMINI_MS": "12.75",
                "DIJKSTRA_MATCH": "5",
                "DIJKSTRA_TOTAL": "5",
                "DIJKSTRA_MISMATCH": "0",
                "DIJKSTRA_GEMINI_MATCH": "5",
                "DIJKSTRA_GEMINI_TOTAL": "5",
                "DIJKSTRA_GEMINI_MISMATCH": "0",
                "STRUCTURAL_VALIDATION_COUNTS_JSON": json.dumps({"dijkstra_baseline": {"valid": 5, "total": 5, "invalid": 0}}),
                "BUILD_PROVENANCE_JSON": json.dumps({"toolchains": {"gcc": {"version": "gcc 13"}}}),
            }
            metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

            result = self.run_create_result(
                workdir=workdir,
                env_overrides={
                    "METRICS_JSON_PATH": str(metrics_path),
                    # Intentionally conflicting values to ensure JSON is preferred.
                    "ALGORITHM_INPUT": "vf3",
                    "EXIT_CODE": "1",
                },
            )

            self.assertEqual(result.get("algorithm"), "dijkstra")
            self.assertEqual(result.get("status"), "success")
            self.assertEqual(result.get("request_id"), "req-structured")
            self.assertEqual(result.get("iterations"), 5)
            self.assertEqual(result.get("warmup"), 1)
            self.assertAlmostEqual(float(result.get("run_duration_ms")), 321.5, places=3)
            self.assertEqual(result.get("inputs", {}).get("graph_family"), "barabasi_albert")
            self.assertEqual(result.get("inputs", {}).get("seed"), 98765)
            self.assertAlmostEqual(result.get("timings_ms", {}).get("baseline"), 10.25, places=6)
            self.assertAlmostEqual(result.get("timings_ms", {}).get("chatgpt"), 11.5, places=6)
            self.assertAlmostEqual(result.get("timings_ms", {}).get("gemini"), 12.75, places=6)
            self.assertEqual(result.get("structural_validation", {}).get("dijkstra_baseline", {}).get("invalid"), 0)
            self.assertEqual(result.get("provenance", {}).get("toolchains", {}).get("gcc", {}).get("version"), "gcc 13")

    def test_falls_back_to_env_when_metrics_json_missing(self):
        with tempfile.TemporaryDirectory(prefix="capstone-test-result-json-env-") as tmp:
            workdir = Path(tmp)
            outputs = workdir / "outputs"
            outputs.mkdir(parents=True, exist_ok=True)
            (outputs / "result.txt").write_text("runtime failure text\n", encoding="utf-8")

            result = self.run_create_result(
                workdir=workdir,
                env_overrides={
                    "METRICS_JSON_PATH": str(outputs / "does-not-exist.json"),
                    "ALGORITHM_INPUT": "vf3",
                    "EXIT_CODE": "1",
                    "REQUEST_ID_INPUT": "req-fallback",
                    "INPUT_MODE_INPUT": "premade",
                    "INPUT_FILES_INPUT": "data/a.vf,data/b.vf",
                    "ITERATIONS": "2",
                    "WARMUP": "0",
                    "VF3_BASE_FIRST_MS": "1.0",
                    "VF3_BASE_ALL_MS": "2.0",
                },
            )

            self.assertEqual(result.get("algorithm"), "vf3")
            self.assertEqual(result.get("status"), "error")
            self.assertEqual(result.get("request_id"), "req-fallback")
            self.assertEqual(result.get("iterations"), 2)
            self.assertEqual(result.get("warmup"), 0)
            self.assertAlmostEqual(result.get("timings_ms", {}).get("baseline_first"), 1.0, places=6)
            self.assertAlmostEqual(result.get("timings_ms", {}).get("baseline_all"), 2.0, places=6)

    def test_reads_dynamic_json_metric_fields(self):
        with tempfile.TemporaryDirectory(prefix="capstone-test-result-json-dynamic-") as tmp:
            workdir = Path(tmp)
            outputs = workdir / "outputs"
            outputs.mkdir(parents=True, exist_ok=True)
            (outputs / "result.txt").write_text("dynamic runner output\n", encoding="utf-8")

            metrics_path = outputs / "run_metrics.json"
            metrics = {
                "ALGORITHM_INPUT": "dijkstra",
                "EXIT_CODE": "0",
                "INPUT_MODE_INPUT": "generate",
                "GENERATOR_N_INPUT": "12",
                "GENERATOR_DENSITY_INPUT": "0.2",
                "SEED_USED": "42",
                "ITERATIONS": "2",
                "WARMUP": "1",
                "RUN_DURATION_MS": "12.5",
                "TIMINGS_MS_JSON": json.dumps({"baseline": 1.5, "claude": 2.0}),
                "TIMINGS_MS_STDEV_JSON": json.dumps({"baseline": 0.1, "claude": 0.2}),
                "MEMORY_KB_JSON": json.dumps({"baseline": 100, "claude": 120}),
                "MEMORY_KB_STDEV_JSON": json.dumps({"baseline": 1, "claude": 2}),
                "MATCH_COUNTS_JSON": json.dumps({"claude": {"matches": 2, "total": 2, "mismatches": 0}}),
                "WITNESS_COUNTS_JSON": json.dumps({"claude": {"valid": 2, "required": 2, "missing": 0}}),
                "VARIANT_METADATA_JSON": json.dumps(
                    [
                        {"variant_id": "dijkstra_baseline", "label": "Dijkstra Baseline", "timing_key": "baseline"},
                        {"variant_id": "dijkstra_claude", "label": "Dijkstra Claude", "timing_key": "claude"},
                    ]
                ),
            }
            metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

            result = self.run_create_result(
                workdir=workdir,
                env_overrides={"METRICS_JSON_PATH": str(metrics_path)},
            )

            self.assertEqual(result.get("status"), "success")
            self.assertAlmostEqual(result.get("timings_ms", {}).get("baseline"), 1.5, places=6)
            self.assertAlmostEqual(result.get("timings_ms", {}).get("claude"), 2.0, places=6)
            self.assertEqual(result.get("memory_kb", {}).get("claude"), 120)
            self.assertEqual(result.get("match_counts", {}).get("claude", {}).get("mismatches"), 0)
            self.assertEqual(result.get("witness_counts", {}).get("claude", {}).get("valid"), 2)
            self.assertEqual(len(result.get("variant_metadata", [])), 2)


if __name__ == "__main__":
    unittest.main()
