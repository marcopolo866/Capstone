"""Regression tests for solver discovery catalog shape and baseline injection."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOLVER_DISCOVERY_PATH = REPO_ROOT / "scripts" / "solver_discovery.py"


def load_solver_discovery_module():
    spec = importlib.util.spec_from_file_location("solver_discovery_test_module", SOLVER_DISCOVERY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load solver discovery module: {SOLVER_DISCOVERY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SolverDiscoveryTests(unittest.TestCase):
    def test_catalog_includes_sp_via_buckets_and_baseline_rows(self):
        module = load_solver_discovery_module()
        catalog = module.build_catalog(REPO_ROOT)

        by_algorithm = catalog.get("by_algorithm", {})
        self.assertIn("sp_via", by_algorithm)

        solver_ids = {str(row.get("variant_id") or "") for row in catalog.get("solvers", [])}
        self.assertIn("dijkstra_baseline", solver_ids)
        self.assertIn("dijkstra_dial", solver_ids)
        self.assertIn("sp_via_baseline", solver_ids)
        self.assertIn("sp_via_dial", solver_ids)

    def test_shortest_path_via_filename_maps_to_sp_via(self):
        module = load_solver_discovery_module()
        with tempfile.TemporaryDirectory(prefix="capstone-solver-discovery-") as tmp:
            repo_root = Path(tmp)
            src_dir = repo_root / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / "[ShortestPathVia][TESTMODEL][csv].cpp").write_text(
                "int main(){return 0;}\n",
                encoding="utf-8",
            )
            variants = module.discover_variants(repo_root)

        self.assertEqual(len(variants), 1)
        variant = variants[0]
        self.assertEqual(variant.family, "sp_via")
        self.assertEqual(variant.algorithm, "sp_via")
        self.assertEqual(variant.variant_id, "sp_via_testmodel")


if __name__ == "__main__":
    unittest.main()
