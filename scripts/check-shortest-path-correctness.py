#!/usr/bin/env python3
"""Validate plain shortest-path solvers against a trusted oracle."""

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

from utilities.benchmark_validation import extract_path_tokens, validate_shortest_path_result


def resolve_binary(base_rel: str) -> Path | None:
    path = (REPO_ROOT / base_rel).resolve()
    if path.is_file():
        return path
    exe = path.with_suffix(path.suffix + ".exe")
    if exe.is_file():
        return exe
    return None


def parse_dijkstra_distance(output_text: str) -> str | None:
    text = str(output_text or "").strip()
    if not text:
        return None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or re.match(r"(?i)^runtime\s*:", line):
            continue
        token = line.split(";", 1)[0].strip()
        if not token:
            continue
        if token.upper() in {"INF", "INFINITY"} or token == "-1":
            return "INF"
        if re.fullmatch(r"[+-]?\d+", token):
            try:
                value = int(token)
            except Exception:
                continue
            return "INF" if value < 0 else str(value)
        match = re.search(r"(?i)\bdistance\s*[:=]\s*([+-]?\d+|INF|INFINITY)\b", line)
        if not match:
            continue
        raw_value = str(match.group(1)).strip()
        if raw_value.upper() in {"INF", "INFINITY"}:
            return "INF"
        try:
            parsed = int(raw_value)
        except Exception:
            continue
        return "INF" if parsed < 0 else str(parsed)
    return None


def run_solver(binary: Path, input_path: Path) -> tuple[str | None, list[str]]:
    completed = subprocess.run(
        [str(binary), str(input_path)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"{binary.name} failed with code {completed.returncode}: {detail[:4000]}")
    combined = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    return parse_dijkstra_distance(combined), extract_path_tokens(combined)


def write_case_csv(path: Path, labels: list[str], edges: list[tuple[int, int, int]], start_label: str, target_label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"# start={start_label} target={target_label}\n")
        fh.write("source,target,weight\n")
        for u, v, w in edges:
            fh.write(f"{labels[u]},{labels[v]},{int(w)}\n")


def build_random_case(seed: int) -> tuple[list[str], list[tuple[int, int, int]], str, str]:
    rng = random.Random(seed)
    n = rng.randint(6, 28)
    labels = [f"v{i}" for i in range(n)]
    edges_map: dict[tuple[int, int], int] = {}
    for i in range(n - 1):
        edges_map[(i, i + 1)] = rng.randint(1, 20)
    max_edges = n * (n - 1)
    target_edges = max(n - 1, min(max_edges, int(round(rng.uniform(0.08, 0.35) * max_edges))))
    attempts = 0
    while len(edges_map) < target_edges and attempts < target_edges * 12:
        u = rng.randrange(n)
        v = rng.randrange(n)
        attempts += 1
        if u == v or (u, v) in edges_map:
            continue
        edges_map[(u, v)] = rng.randint(1, 20)
    return labels, [(u, v, w) for (u, v), w in edges_map.items()], labels[0], labels[-1]


def deterministic_no_path_cases() -> list[tuple[list[str], list[tuple[int, int, int]], str, str]]:
    labels = [f"v{i}" for i in range(6)]
    return [
        (labels, [(0, 1, 2), (1, 2, 2), (3, 4, 1), (4, 5, 1)], "v0", "v5"),
        (labels, [(0, 1, 3), (1, 2, 4), (4, 5, 1)], "v0", "v4"),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check plain shortest-path correctness across available binaries.")
    parser.add_argument("--iterations", type=int, default=20, help="Number of random graph cases to test.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    iterations = max(1, int(args.iterations))

    required = [("dijkstra_baseline", "baselines/dijkstra")]
    optional = [
        ("dijkstra_dial", "baselines/dial"),
        ("dijkstra_chatgpt", "src/dijkstra_chatgpt"),
        ("dijkstra_gemini", "src/dijkstra_gemini"),
        ("dijkstra_claude", "src/dijkstra_claude"),
    ]
    solvers: list[tuple[str, Path]] = []
    for name, rel in required:
        resolved = resolve_binary(rel)
        if not resolved:
            raise RuntimeError(f"Missing required shortest-path solver binary: {rel}")
        solvers.append((name, resolved))
    skipped: list[str] = []
    for name, rel in optional:
        resolved = resolve_binary(rel)
        if resolved:
            solvers.append((name, resolved))
        else:
            skipped.append(f"{name} ({rel})")

    cases = deterministic_no_path_cases()
    for idx in range(iterations):
        cases.append(build_random_case(1701 + idx))

    with tempfile.TemporaryDirectory(prefix="shortest_path_check_") as tmp:
        tmp_dir = Path(tmp)
        for case_idx, case in enumerate(cases):
            labels, edges, start_label, target_label = case
            input_path = tmp_dir / f"case_{case_idx + 1:03d}.csv"
            write_case_csv(input_path, labels, edges, start_label, target_label)
            for solver_name, solver_path in solvers:
                reported_distance, path_tokens = run_solver(solver_path, input_path)
                validation = validate_shortest_path_result(
                    input_path=input_path,
                    reported_distance=reported_distance,
                    path_tokens=path_tokens,
                )
                if not bool(validation.get("valid")):
                    raise AssertionError(f"{solver_name}: {validation.get('error')}")

    print(f"[check-shortest-path-correctness] validated {len(cases)} cases across {len(solvers)} solver(s).")
    if skipped:
        print("[check-shortest-path-correctness] skipped optional solvers:")
        for item in skipped:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
