#!/usr/bin/env python3
"""Validate Glasgow-style subgraph solvers by solution-count parity only."""

from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_binary(base_rel: str) -> Path | None:
    path = (REPO_ROOT / base_rel).resolve()
    if path.is_file():
        return path
    exe = path.with_suffix(path.suffix + ".exe")
    if exe.is_file():
        return exe
    return None


def parse_solution_count(text: str) -> int | None:
    src = str(text or "").strip()
    if not src:
        return None
    patterns = [
        r"(?im)\bsolution[_\s-]*count\s*[:=]\s*(-?\d+)\b",
        r"(?im)\bsolutions?\s*(?:count|found|total)?\s*[:=]\s*(-?\d+)\b",
        r"(?im)\b(-?\d+)\s+solutions?\b",
    ]
    for pat in patterns:
        match = re.search(pat, src)
        if not match:
            continue
        try:
            return int(match.group(1))
        except ValueError:
            continue
    for line in [line.strip() for line in src.splitlines() if line.strip()]:
        if re.fullmatch(r"-?\d+", line):
            return int(line)
    return None


def run_solver(command: list[str], label: str) -> str:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"{label} failed with exit={completed.returncode}: {detail[:2000]}")
    return (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")


def write_case(path_pattern: Path, path_target: Path, pattern_rows: list[str], target_rows: list[str]) -> None:
    path_pattern.write_text("\n".join(pattern_rows).rstrip() + "\n", encoding="utf-8")
    path_target.write_text("\n".join(target_rows).rstrip() + "\n", encoding="utf-8")


def build_generated_case(seed: int, n: int, k: int, density: float, out_dir: Path) -> tuple[Path, Path]:
    cmd = [
        sys.executable,
        "utilities/generate_graphs.py",
        "--algorithm",
        "subgraph",
        "--n",
        str(n),
        "--k",
        str(k),
        "--density",
        str(density),
        "--seed",
        str(seed),
        "--out-dir",
        str(out_dir),
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=True,
    )
    parts = [p.strip() for p in str(completed.stdout or "").strip().split(",") if p.strip()]
    if len(parts) < 2:
        raise RuntimeError(f"Generator did not return LAD files for seed {seed}: {completed.stdout}")
    return Path(parts[0]).resolve(), Path(parts[1]).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Glasgow count correctness.")
    parser.add_argument("--generated-cases", type=int, default=6, help="Number of generated random cases.")
    parser.add_argument("--base-seed", type=int, default=1729, help="Base seed for generated cases.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    baseline = resolve_binary("baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver")
    if not baseline:
        raise RuntimeError("Missing required Glasgow baseline binary.")

    optional = [
        ("glasgow_chatgpt", resolve_binary("src/glasgow_chatgpt")),
        ("glasgow_gemini", resolve_binary("src/glasgow_gemini")),
        ("glasgow_claude", resolve_binary("src/glasgow_claude")),
    ]
    solvers = [(name, path) for name, path in optional if path is not None]
    skipped = [name for name, path in optional if path is None]
    if not solvers:
        print("[check-subgraph-count-correctness] No optional Glasgow LLM binaries found; skipping.")
        return 0

    with tempfile.TemporaryDirectory(prefix="glasgow-count-check-") as tmp:
        tmp_dir = Path(tmp)
        cases: list[tuple[Path, Path, str]] = []

        pos_pattern = tmp_dir / "hand_pattern_pos.lad"
        pos_target = tmp_dir / "hand_target_pos.lad"
        write_case(
            pos_pattern,
            pos_target,
            ["3", "1 2 1 2", "1 2 0 2", "1 2 0 1"],
            ["5", "1 2 1 2", "1 3 0 2 3", "1 3 0 1 3", "1 2 1 2", "1 0"],
        )
        cases.append((pos_pattern, pos_target, "hand_triangle_positive"))

        neg_pattern = tmp_dir / "hand_pattern_neg.lad"
        neg_target = tmp_dir / "hand_target_neg.lad"
        write_case(
            neg_pattern,
            neg_target,
            ["3", "1 2 1 2", "1 2 0 2", "1 2 0 1"],
            ["4", "1 1 1", "1 2 0 2", "1 2 1 3", "1 1 2"],
        )
        cases.append((neg_pattern, neg_target, "hand_triangle_negative"))

        rng = random.Random(int(args.base_seed))
        for idx in range(max(0, int(args.generated_cases))):
            seed = int(args.base_seed) + idx + 1
            n = rng.randint(10, 26)
            k = rng.randint(4, min(8, n - 1))
            density = rng.uniform(0.08, 0.28)
            out_dir = tmp_dir / f"generated_{idx + 1:02d}"
            pattern, target = build_generated_case(seed=seed, n=n, k=k, density=density, out_dir=out_dir)
            cases.append((pattern, target, f"generated_seed_{seed}"))

        validated = 0
        for pattern_path, target_path, label in cases:
            baseline_out = run_solver(
                [
                    str(baseline),
                    "--count-solutions",
                    "--format",
                    "vertexlabelledlad",
                    str(pattern_path),
                    str(target_path),
                ],
                f"baseline {label}",
            )
            baseline_count = parse_solution_count(baseline_out)
            if baseline_count is None:
                raise RuntimeError(f"Could not parse baseline solution count for {label}.")
            if label == "hand_triangle_positive" and int(baseline_count) <= 0:
                raise RuntimeError(f"Glasgow baseline returned no match for known-positive case: {label}")
            if label == "hand_triangle_negative" and int(baseline_count) != 0:
                raise RuntimeError(
                    f"Glasgow baseline returned unexpected positive count for known-negative case: {label} -> {baseline_count}"
                )

            for solver_name, solver_bin in solvers:
                output = run_solver(
                    [str(solver_bin), str(pattern_path), str(target_path)],
                    f"{solver_name} {label}",
                )
                solver_count = parse_solution_count(output)
                if solver_count is None:
                    raise RuntimeError(f"Could not parse {solver_name} solution count for {label}.")
                if int(solver_count) != int(baseline_count):
                    raise RuntimeError(
                        f"{solver_name} count mismatch for {label}: baseline={baseline_count}, solver={solver_count}"
                    )
                validated += 1

    print(
        f"[check-subgraph-count-correctness] validated {validated} solver/case combinations "
        f"across {len(solvers)} solver(s)."
    )
    if skipped:
        print("[check-subgraph-count-correctness] skipped missing solvers:")
        for name in skipped:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
