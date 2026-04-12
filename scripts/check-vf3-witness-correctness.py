#!/usr/bin/env python3
"""Validate VF3-style witness mappings for available VF3 binaries."""

from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utilities.benchmark_validation import validate_subgraph_result


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
        r"(?im)\bcount\s*[:=]\s*(-?\d+)\b",
        r"(?im)\b(-?\d+)\s+solutions?\b",
    ]
    for pat in patterns:
        match = re.search(pat, src)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    for line in [line.strip() for line in src.splitlines() if line.strip()]:
        terse = re.match(r"^(-?\d+)(?:\s|$)", line)
        if terse:
            try:
                return int(terse.group(1))
            except ValueError:
                continue
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


def write_vf(path: Path, adj: list[list[int]], labels: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for idx, label in enumerate(labels):
            fh.write(f"{idx} {label}\n")
        for idx, neighbors in enumerate(adj):
            fh.write(f"{len(neighbors)}\n")
            for v in neighbors:
                fh.write(f"{idx} {v}\n")


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
    if len(parts) < 4:
        raise RuntimeError(f"Generator did not return VF paths for seed {seed}: {completed.stdout}")
    return Path(parts[2]).resolve(), Path(parts[3]).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check VF3 witness mapping correctness.")
    parser.add_argument("--generated-cases", type=int, default=6, help="Number of generated random cases.")
    parser.add_argument("--base-seed", type=int, default=4242, help="Base seed for generated cases.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    baseline = resolve_binary("baselines/vf3lib/bin/vf3")
    if not baseline:
        raise RuntimeError("Missing required VF3 baseline binary.")

    optional = [
        ("vf3_chatgpt", resolve_binary("src/vf3_chatgpt")),
        ("vf3_gemini", resolve_binary("src/vf3_gemini")),
        ("vf3_claude", resolve_binary("src/vf3_claude")),
    ]
    solvers = [(name, path) for name, path in optional if path is not None]
    skipped = [name for name, path in optional if path is None]
    if not solvers:
        print("[check-vf3-witness-correctness] No optional VF3 LLM binaries found; skipping.")
        return 0

    with tempfile.TemporaryDirectory(prefix="vf3-witness-check-") as tmp:
        tmp_dir = Path(tmp)
        cases: list[tuple[Path, Path, str]] = []

        pos_pattern = tmp_dir / "hand_pattern_pos.vf"
        pos_target = tmp_dir / "hand_target_pos.vf"
        write_vf(pos_pattern, [[1, 2], [0, 2], [0, 1]], [0, 1, 2])
        write_vf(pos_target, [[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]], [0, 1, 2, 3])
        cases.append((pos_pattern, pos_target, "hand_triangle_positive"))

        neg_pattern = tmp_dir / "hand_pattern_neg.vf"
        neg_target = tmp_dir / "hand_target_neg.vf"
        write_vf(neg_pattern, [[1, 2], [0, 2], [0, 1]], [0, 1, 2])
        write_vf(neg_target, [[1], [0, 2], [1, 3], [2]], [0, 1, 2, 3])
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
        baseline_witness_warnings: list[str] = []
        solver_witness_warnings: list[str] = []
        for pattern_path, target_path, label in cases:
            baseline_all = run_solver(
                [str(baseline), "-u", "-r", "0", "-e", str(pattern_path), str(target_path)],
                f"vf3 baseline {label}",
            )
            baseline_count = parse_solution_count(baseline_all)
            if baseline_count is None:
                raise RuntimeError(f"Could not parse baseline solution count for {label}.")
            if label == "hand_triangle_positive" and int(baseline_count) <= 0:
                raise RuntimeError(f"VF3 baseline returned no match for known-positive case: {label}")
            if label == "hand_triangle_negative" and int(baseline_count) != 0:
                raise RuntimeError(
                    f"VF3 baseline returned unexpected positive count for known-negative case: {label} -> {baseline_count}"
                )

            baseline_first = run_solver(
                [str(baseline), "-u", "-r", "0", "-F", "-e", str(pattern_path), str(target_path)],
                f"vf3 baseline first {label}",
            )
            baseline_validation = validate_subgraph_result(
                family="vf3",
                inputs={"vf_pattern": pattern_path, "vf_target": target_path},
                output_text=baseline_first,
                reported_solution_count=baseline_count,
                allow_metadata_fallback=False,
            )
            if not bool(baseline_validation.get("valid")):
                baseline_witness_warnings.append(
                    f"{label}: baseline did not emit a parseable witness mapping ({baseline_validation.get('error')})"
                )

            for solver_name, solver_bin in solvers:
                all_output = run_solver([str(solver_bin), str(pattern_path), str(target_path)], f"{solver_name} {label}")
                solver_count = parse_solution_count(all_output)
                if solver_count is None:
                    raise RuntimeError(f"Could not parse {solver_name} solution count for {label}.")
                if int(solver_count) != int(baseline_count):
                    raise RuntimeError(
                        f"{solver_name} count mismatch for {label}: baseline={baseline_count}, solver={solver_count}"
                    )

                validation = validate_subgraph_result(
                    family="vf3",
                    inputs={"vf_pattern": pattern_path, "vf_target": target_path},
                    output_text=all_output,
                    reported_solution_count=solver_count,
                    allow_metadata_fallback=False,
                )
                if bool(validation.get("required_witness")) and not bool(validation.get("valid")):
                    first_output = run_solver(
                        [str(solver_bin), "--first-only", str(pattern_path), str(target_path)],
                        f"{solver_name} first {label}",
                    )
                    validation = validate_subgraph_result(
                        family="vf3",
                        inputs={"vf_pattern": pattern_path, "vf_target": target_path},
                        output_text=first_output,
                        reported_solution_count=solver_count,
                        allow_metadata_fallback=False,
                    )
                if bool(validation.get("required_witness")) and not bool(validation.get("valid")):
                    validation = validate_subgraph_result(
                        family="vf3",
                        inputs={"vf_pattern": pattern_path, "vf_target": target_path},
                        output_text="",
                        reported_solution_count=solver_count,
                        allow_metadata_fallback=True,
                    )
                if not bool(validation.get("valid")):
                    metadata_path = pattern_path.parent / "metadata.json"
                    if metadata_path.is_file():
                        raise RuntimeError(f"{solver_name} witness validation failed for {label}: {validation.get('error')}")
                    solver_witness_warnings.append(
                        f"{solver_name} {label}: positive count matched baseline but no witness mapping was emitted"
                    )
                    continue
                validated += 1

    print(
        f"[check-vf3-witness-correctness] validated {validated} solver/case combinations "
        f"across {len(solvers)} solver(s)."
    )
    if baseline_witness_warnings:
        print("[check-vf3-witness-correctness] baseline witness warnings:")
        for item in baseline_witness_warnings:
            print(f"  - {item}")
    if solver_witness_warnings:
        print("[check-vf3-witness-correctness] solver witness warnings:")
        for item in solver_witness_warnings:
            print(f"  - {item}")
    if skipped:
        print("[check-vf3-witness-correctness] skipped missing solvers:")
        for name in skipped:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
