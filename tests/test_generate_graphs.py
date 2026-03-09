import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GEN_SCRIPT = REPO_ROOT / "utilities" / "generate_graphs.py"


class GenerateGraphsCliTests(unittest.TestCase):
    def run_generator(self, *, algorithm: str, n: int, k: int | None, density: float, seed: int, out_dir: Path):
        cmd = [
            sys.executable,
            str(GEN_SCRIPT),
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
        if k is not None:
            cmd.extend(["--k", str(k)])
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        files = [part.strip() for part in completed.stdout.strip().split(",") if part.strip()]
        return files

    def test_dijkstra_generation_writes_csv_and_metadata(self):
        with tempfile.TemporaryDirectory(prefix="capstone-test-dijkstra-") as tmp:
            out_dir = Path(tmp) / "out"
            files = self.run_generator(
                algorithm="dijkstra",
                n=12,
                k=None,
                density=0.2,
                seed=1337,
                out_dir=out_dir,
            )

            self.assertEqual(len(files), 1, "dijkstra generation should emit exactly one file path")
            generated_csv = Path(files[0])
            self.assertTrue(generated_csv.is_file(), f"missing generated file: {generated_csv}")

            metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("algorithm"), "dijkstra")
            self.assertEqual(metadata.get("n"), 12)
            self.assertEqual(metadata.get("seed"), 1337)
            self.assertEqual(len(metadata.get("files", [])), 1)

    def test_subgraph_generation_is_reproducible_for_fixed_seed(self):
        with tempfile.TemporaryDirectory(prefix="capstone-test-subgraph-a-") as tmp_a, tempfile.TemporaryDirectory(
            prefix="capstone-test-subgraph-b-"
        ) as tmp_b:
            out_a = Path(tmp_a) / "out"
            out_b = Path(tmp_b) / "out"

            files_a = self.run_generator(
                algorithm="subgraph",
                n=24,
                k=7,
                density=0.17,
                seed=424242,
                out_dir=out_a,
            )
            files_b = self.run_generator(
                algorithm="subgraph",
                n=24,
                k=7,
                density=0.17,
                seed=424242,
                out_dir=out_b,
            )

            self.assertEqual(len(files_a), 4)
            self.assertEqual(len(files_b), 4)

            for path_a, path_b in zip(files_a, files_b):
                data_a = Path(path_a).read_text(encoding="utf-8")
                data_b = Path(path_b).read_text(encoding="utf-8")
                self.assertEqual(data_a, data_b, f"generated files differ for fixed seed: {path_a} vs {path_b}")

            meta_a = json.loads((out_a / "metadata.json").read_text(encoding="utf-8"))
            meta_b = json.loads((out_b / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(meta_a.get("seed"), 424242)
            self.assertEqual(meta_b.get("seed"), 424242)
            self.assertEqual(meta_a.get("pattern_nodes"), meta_b.get("pattern_nodes"))


if __name__ == "__main__":
    unittest.main()
