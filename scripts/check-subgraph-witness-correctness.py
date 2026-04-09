#!/usr/bin/env python3
"""Validate subgraph witness mappings for available Glasgow-style LLM solvers."""

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
    lines = [line.strip() for line in src.splitlines() if line.strip()]
    for line in lines:
        if re.fullmatch(r"-?\d+", line):
            return int(line)
    return None


def parse_int_tokens(line: str) -> list[int]:
    return [int(token) for token in re.findall(r"-?\d+", str(line or ""))]


def parse_lad_graph(path: Path) -> list[list[int]]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise RuntimeError(f"Empty LAD graph file: {path}")
    n_tokens = parse_int_tokens(lines[0])
    if not n_tokens:
        raise RuntimeError(f"Invalid LAD header in {path}")
    n = max(0, int(n_tokens[0]))
    adj: list[set[int]] = [set() for _ in range(n)]
    for u in range(n):
        if u + 1 >= len(lines):
            break
        values = parse_int_tokens(lines[u + 1])
        if not values:
            continue

        # Prefer vertex-labelled LAD rows: "<label> <degree> <neighbors...>".
        # This avoids ambiguity for rows like "2 1 3", which can also satisfy
        # an unlabeled shape check but should be interpreted as labelled.
        neighbors: list[int]
        labeled_degree = int(values[1]) if len(values) >= 2 else -1
        if len(values) >= 2 and labeled_degree >= 0 and len(values) >= 2 + labeled_degree:
            neighbors = values[2 : 2 + labeled_degree]
        else:
            unlabeled_degree = int(values[0])
            if unlabeled_degree < 0:
                continue
            neighbors = values[1 : 1 + unlabeled_degree]

        for v in neighbors:
            if 0 <= v < n and v != u:
                adj[u].add(v)
                adj[v].add(u)
    return [sorted(row) for row in adj]


def extract_mappings(output_text: str, limit: int = 32) -> list[dict[int, int]]:
    out: list[dict[int, int]] = []
    seen: set[str] = set()
    for raw_line in str(output_text or "").replace("\r", "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pairs = [(m.group(1), m.group(2)) for m in re.finditer(r"\(\s*(\d+)\s*->\s*(\d+)\s*\)", line)]
        if not pairs:
            continue
        mapping: dict[int, int] = {}
        for p_raw, t_raw in pairs:
            try:
                mapping[int(p_raw)] = int(t_raw)
            except ValueError:
                continue
        if not mapping:
            continue
        key = str(sorted(mapping.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(mapping)
        if len(out) >= max(1, int(limit)):
            break
    return out


def edge_key(u: int, v: int) -> tuple[int, int] | None:
    if u == v:
        return None
    return (u, v) if u < v else (v, u)


def build_edge_set(adj: list[list[int]]) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for u, neighbors in enumerate(adj):
        for v in neighbors:
            ek = edge_key(u, v)
            if ek is not None:
                edges.add(ek)
    return edges


def is_valid_mapping(pattern_adj: list[list[int]], target_adj: list[list[int]], mapping: dict[int, int]) -> bool:
    p_n = len(pattern_adj)
    t_n = len(target_adj)
    if len(mapping) < p_n:
        return False

    normalized: dict[int, int] = {}
    used: set[int] = set()
    for p in range(p_n):
        t = mapping.get(p)
        if t is None:
            return False
        t = int(t)
        if t < 0 or t >= t_n:
            return False
        if t in used:
            return False
        used.add(t)
        normalized[p] = t

    target_edges = build_edge_set(target_adj)
    for u, neighbors in enumerate(pattern_adj):
        for v in neighbors:
            ek_p = edge_key(u, v)
            if ek_p is None:
                continue
            tu = normalized.get(u)
            tv = normalized.get(v)
            if tu is None or tv is None:
                return False
            ek_t = edge_key(tu, tv)
            if ek_t is None or ek_t not in target_edges:
                return False
    return True


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
    parser = argparse.ArgumentParser(description="Check Glasgow witness mapping correctness.")
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
        print("[check-subgraph-witness-correctness] No optional Glasgow LLM binaries found; skipping.")
        return 0

    with tempfile.TemporaryDirectory(prefix="glasgow-witness-check-") as tmp:
        tmp_dir = Path(tmp)
        cases: list[tuple[Path, Path, str]] = []

        # Hand-crafted positive triangle case.
        pos_pattern = tmp_dir / "hand_pattern_pos.lad"
        pos_target = tmp_dir / "hand_target_pos.lad"
        write_case(
            pos_pattern,
            pos_target,
            [
                "3",
                "1 2 1 2",
                "1 2 0 2",
                "1 2 0 1",
            ],
            [
                "5",
                "1 2 1 2",
                "1 3 0 2 3",
                "1 3 0 1 3",
                "1 2 1 2",
                "1 0",
            ],
        )
        cases.append((pos_pattern, pos_target, "hand_triangle_positive"))

        # Hand-crafted negative case.
        neg_pattern = tmp_dir / "hand_pattern_neg.lad"
        neg_target = tmp_dir / "hand_target_neg.lad"
        write_case(
            neg_pattern,
            neg_target,
            [
                "3",
                "1 2 1 2",
                "1 2 0 2",
                "1 2 0 1",
            ],
            [
                "4",
                "1 1 1",
                "1 2 0 2",
                "1 2 1 3",
                "1 1 2",
            ],
        )
        cases.append((neg_pattern, neg_target, "hand_triangle_negative"))

        rng = random.Random(int(args.base_seed))
        generated_cases = max(0, int(args.generated_cases))
        for idx in range(generated_cases):
            seed = int(args.base_seed) + idx + 1
            n = rng.randint(10, 26)
            k = rng.randint(4, min(8, n - 1))
            density = rng.uniform(0.08, 0.28)
            out_dir = tmp_dir / f"generated_{idx + 1:02d}"
            pattern, target = build_generated_case(seed=seed, n=n, k=k, density=density, out_dir=out_dir)
            cases.append((pattern, target, f"generated_seed_{seed}"))

        validated = 0
        for pattern_path, target_path, label in cases:
            pattern_adj = parse_lad_graph(pattern_path)
            target_adj = parse_lad_graph(target_path)
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

            for solver_name, solver_bin in solvers:
                output = run_solver(
                    [str(solver_bin), str(pattern_path), str(target_path), "--print-mappings"],
                    f"{solver_name} {label}",
                )
                solver_count = parse_solution_count(output)
                if solver_count is None:
                    raise RuntimeError(f"Could not parse {solver_name} solution count for {label}.")
                if int(solver_count) != int(baseline_count):
                    raise RuntimeError(
                        f"{solver_name} count mismatch for {label}: baseline={baseline_count}, solver={solver_count}"
                    )

                if int(solver_count) > 0:
                    mappings = extract_mappings(output, limit=64)
                    if not mappings:
                        raise RuntimeError(f"{solver_name} returned no witness mapping for positive case {label}.")
                    has_valid = any(is_valid_mapping(pattern_adj, target_adj, m) for m in mappings)
                    if not has_valid:
                        raise RuntimeError(f"{solver_name} produced only invalid witness mappings for {label}.")
                validated += 1

    print(
        f"[check-subgraph-witness-correctness] validated {validated} solver/case combinations "
        f"across {len(solvers)} solver(s)."
    )
    if skipped:
        print("[check-subgraph-witness-correctness] skipped missing solvers:")
        for name in skipped:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
