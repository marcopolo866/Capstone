import tempfile
import unittest
from pathlib import Path

from utilities.benchmark_validation import validate_shortest_path_result


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

if __name__ == "__main__":
    unittest.main()
