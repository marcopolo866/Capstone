import tempfile
import unittest
from pathlib import Path

from utilities.benchmark_validation import validate_shortest_path_result, validate_subgraph_result


class BenchmarkValidationTests(unittest.TestCase):
    def test_validate_shortest_path_result_accepts_valid_path(self):
        with tempfile.TemporaryDirectory(prefix="capstone-test-validation-sp-") as tmp:
            path = Path(tmp) / "graph.csv"
            path.write_text(
                "# start=v0 target=v3\n"
                "source,target,weight\n"
                "v0,v1,1\n"
                "v1,v2,2\n"
                "v2,v3,3\n",
                encoding="utf-8",
            )
            result = validate_shortest_path_result(
                input_path=path,
                reported_distance="6",
                path_tokens=["v0", "v1", "v2", "v3"],
            )
        self.assertTrue(result.get("valid"))
        self.assertTrue(result.get("path_valid"))

    def test_validate_subgraph_result_accepts_valid_vf3_mapping(self):
        with tempfile.TemporaryDirectory(prefix="capstone-test-validation-vf3-") as tmp:
            tmp_dir = Path(tmp)
            pattern = tmp_dir / "pattern.vf"
            target = tmp_dir / "target.vf"
            pattern.write_text(
                "3\n"
                "0 0\n"
                "1 1\n"
                "2 2\n"
                "2\n"
                "0 1\n"
                "0 2\n"
                "2\n"
                "1 0\n"
                "1 2\n"
                "2\n"
                "2 0\n"
                "2 1\n",
                encoding="utf-8",
            )
            target.write_text(
                "4\n"
                "0 0\n"
                "1 1\n"
                "2 2\n"
                "3 3\n"
                "3\n"
                "0 1\n"
                "0 2\n"
                "0 3\n"
                "3\n"
                "1 0\n"
                "1 2\n"
                "1 3\n"
                "3\n"
                "2 0\n"
                "2 1\n"
                "2 3\n"
                "3\n"
                "3 0\n"
                "3 1\n"
                "3 2\n",
                encoding="utf-8",
            )
            result = validate_subgraph_result(
                family="vf3",
                inputs={"vf_pattern": pattern, "vf_target": target},
                output_text="mapping: 0->0 1->1 2->2\nsolution_count=1\n",
                reported_solution_count=1,
                allow_metadata_fallback=False,
            )
        self.assertTrue(result.get("valid"))
        self.assertEqual(result.get("witness_source"), "solver_output")


if __name__ == "__main__":
    unittest.main()
