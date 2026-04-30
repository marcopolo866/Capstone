"""Regression tests for the GitHub Actions dynamic benchmark runner."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_dynamic_runner_module():
    module_path = REPO_ROOT / ".github" / "scripts" / "run-algorithm-dynamic.py"
    spec = importlib.util.spec_from_file_location("github_dynamic_runner_test_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GithubDynamicRunnerTests(unittest.TestCase):
    def test_glasgow_llm_commands_do_not_include_unsupported_mapping_flag(self):
        module = load_dynamic_runner_module()
        row = module.SolverRow(
            variant_id="glasgow_chatgpt_control",
            family="glasgow",
            algorithm="subgraph",
            role="variant",
            label="Glasgow ChatGPT Control",
            llm_key="chatgpt",
            llm_label="ChatGPT",
            binary_path="src/glasgow_chatgpt_control",
        )
        inputs = {
            "lad_pattern": Path("outputs/generated/subgraph/iter_1/glasgow_pattern.lad"),
            "lad_target": Path("outputs/generated/subgraph/iter_1/glasgow_target.lad"),
        }

        with mock.patch.object(module, "resolve_row_binary", return_value=Path("/tmp/glasgow_chatgpt_control")):
            commands = module.make_mode_commands(row, inputs, via_label="")

        self.assertEqual(
            commands["first"],
            [
                str(Path("/tmp/glasgow_chatgpt_control")),
                str(inputs["lad_pattern"]),
                str(inputs["lad_target"]),
            ],
        )
        self.assertEqual(commands["all"], commands["first"])
        self.assertNotIn("--print-mappings", commands["first"])


if __name__ == "__main__":
    unittest.main()
