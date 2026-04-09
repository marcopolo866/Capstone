import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check-subgraph-witness-correctness.py"


def load_checker_module():
    spec = importlib.util.spec_from_file_location("check_subgraph_witness_correctness", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load checker module from {CHECKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SubgraphWitnessParserTests(unittest.TestCase):
    def test_parse_lad_graph_prefers_vertex_labelled_rows(self):
        checker = load_checker_module()
        pattern_text = "\n".join(
            [
                "7",
                "3 3 1 2 4",
                "0 2 0 2",
                "1 3 0 1 3",
                "2 4 2 4 5 6",
                "3 3 0 3 5",
                "0 2 3 4",
                "2 1 3",
            ]
        )
        with tempfile.TemporaryDirectory(prefix="capstone-test-witness-") as tmp:
            pattern_path = Path(tmp) / "pattern.lad"
            pattern_path.write_text(pattern_text + "\n", encoding="utf-8")
            adj = checker.parse_lad_graph(pattern_path)

        self.assertNotIn(6, adj[1], "ambiguous row should not inject a fake edge 1-6")
        self.assertEqual(adj[6], [3], "vertex 6 should only connect to 3")

    def test_is_valid_mapping_accepts_generated_seed_1730_witness(self):
        checker = load_checker_module()
        pattern_text = "\n".join(
            [
                "7",
                "3 3 1 2 4",
                "0 2 0 2",
                "1 3 0 1 3",
                "2 4 2 4 5 6",
                "3 3 0 3 5",
                "0 2 3 4",
                "2 1 3",
            ]
        )
        target_text = "\n".join(
            [
                "11",
                "0 2 1 3",
                "1 4 0 2 4 5",
                "2 3 1 3 8",
                "3 5 0 2 4 5 7",
                "0 3 1 3 5",
                "1 4 1 3 4 6",
                "2 4 5 7 8 10",
                "3 3 3 6 8",
                "0 4 2 6 7 9",
                "1 2 8 10",
                "2 2 6 9",
            ]
        )

        with tempfile.TemporaryDirectory(prefix="capstone-test-witness-") as tmp:
            pattern_path = Path(tmp) / "pattern.lad"
            target_path = Path(tmp) / "target.lad"
            pattern_path.write_text(pattern_text + "\n", encoding="utf-8")
            target_path.write_text(target_text + "\n", encoding="utf-8")
            pattern_adj = checker.parse_lad_graph(pattern_path)
            target_adj = checker.parse_lad_graph(target_path)

        mapping = {0: 3, 1: 4, 2: 5, 3: 6, 4: 7, 5: 8, 6: 10}
        self.assertTrue(checker.is_valid_mapping(pattern_adj, target_adj, mapping))


if __name__ == "__main__":
    unittest.main()
