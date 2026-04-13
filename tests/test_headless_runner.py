import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from desktop_runner import app, headless_runner


# - These tests cover shared manifest/building behavior that can regress when
#   desktop and headless execution paths drift apart.
# - Prefer asserting on serialized shapes and injected defaults here because
#   those are the contracts external automation depends on.
class HeadlessRunnerTests(unittest.TestCase):
    def test_enforce_baselines_injects_family_baseline(self):
        selected, injected = headless_runner.enforce_baselines("subgraph", ["vf3_chatgpt"])
        self.assertIn("vf3_chatgpt", selected)
        self.assertIn("vf3_baseline", selected)
        self.assertEqual(injected, ["vf3_baseline"])

    def test_build_runtime_config_generates_subgraph_points(self):
        with mock.patch.object(headless_runner, "validate_binaries", lambda _selected: None):
            config = headless_runner.build_runtime_config(
                {
                    "preset": "smoke",
                    "tab_id": "subgraph",
                    "input_mode": "independent",
                    "graph_family": "erdos_renyi",
                    "selected_variants": ["vf3_chatgpt"],
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


if __name__ == "__main__":
    unittest.main()
