#!/usr/bin/env python3
"""Validate SP-Via solvers against a trusted shortest-path-via oracle."""

# - This checker carries its own oracle logic because it validates an aggregate
#   path constraint, not just plain shortest-path output formatting.
# - Keep generated graph assumptions close to the benchmark generator so a local
#   correctness pass is representative of real benchmark inputs.

from __future__ import annotations

import argparse
import heapq
import random
import re
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INF = 10**18


def resolve_binary(base_rel: str) -> Path | None:
    path = (REPO_ROOT / base_rel).resolve()
    if path.is_file():
        return path
    exe = path.with_suffix(path.suffix + ".exe")
    if exe.is_file():
        return exe
    return None


def parse_solver_output(text: str) -> tuple[int | None, list[str]]:
    lines = [line.strip() for line in str(text or "").replace("\r", "").splitlines() if line.strip()]
    cleaned = [line for line in lines if not line.lower().startswith("runtime")]
    if not cleaned:
        return None, []
    line = cleaned[0]
    lowered = line.lower()
    if "no path" in lowered or "inf" in lowered:
        return None, []
    if ";" not in line:
        return None, []
    left, right = line.split(";", 1)
    m = re.search(r"-?\d+", left)
    if not m:
        return None, []
    distance = int(m.group(0))
    path_tokens = re.findall(r"[A-Za-z0-9_.:-]+", right.replace("->", " "))
    return distance, path_tokens


def dijkstra(adj: list[list[tuple[int, int]]], start: int) -> tuple[list[int], list[int]]:
    n = len(adj)
    dist = [INF] * n
    parent = [-1] * n
    dist[start] = 0
    pq: list[tuple[int, int]] = [(0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if d != dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + int(w)
            if nd < dist[v]:
                dist[v] = nd
                parent[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, parent


def reconstruct(parent: list[int], start: int, target: int) -> list[int]:
    out: list[int] = []
    cur = target
    while cur != -1:
        out.append(cur)
        if cur == start:
            break
        cur = parent[cur]
    if not out or out[-1] != start:
        return []
    out.reverse()
    return out


def oracle_shortest_path_via(
    labels: list[str],
    edges: list[tuple[int, int, int]],
    start_idx: int,
    via_idx: int,
    target_idx: int,
) -> tuple[int | None, list[str]]:
    n = len(labels)
    adj: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    for u, v, w in edges:
        adj[u].append((v, int(w)))

    dist_s, parent_s = dijkstra(adj, start_idx)
    dist_v, parent_v = dijkstra(adj, via_idx)
    if dist_s[via_idx] >= INF or dist_v[target_idx] >= INF:
        return None, []

    p1 = reconstruct(parent_s, start_idx, via_idx)
    p2 = reconstruct(parent_v, via_idx, target_idx)
    if not p1 or not p2:
        return None, []
    full = p1 + p2[1:]
    return int(dist_s[via_idx] + dist_v[target_idx]), [labels[idx] for idx in full]


def write_case_csv(
    path: Path,
    labels: list[str],
    edges: list[tuple[int, int, int]],
    start_label: str,
    target_label: str,
    via_label: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"# start={start_label} target={target_label} via={via_label}\n")
        fh.write("source,target,weight\n")
        for u, v, w in edges:
            fh.write(f"{labels[u]},{labels[v]},{int(w)}\n")


def validate_solver_answer(
    *,
    solver_name: str,
    observed_distance: int | None,
    observed_path: list[str],
    expected_distance: int | None,
    labels: list[str],
    edges: list[tuple[int, int, int]],
    start_label: str,
    via_label: str,
    target_label: str,
) -> None:
    if expected_distance is None:
        if observed_distance is not None:
            raise AssertionError(
                f"{solver_name}: expected no-path but got distance={observed_distance} path={observed_path}"
            )
        return

    if observed_distance is None:
        raise AssertionError(f"{solver_name}: expected distance={expected_distance} but got no-path")
    if int(observed_distance) != int(expected_distance):
        raise AssertionError(
            f"{solver_name}: expected distance={expected_distance} got {observed_distance} path={observed_path}"
        )
    if not observed_path:
        raise AssertionError(f"{solver_name}: missing path output for reachable case")
    if observed_path[0] != start_label or observed_path[-1] != target_label:
        raise AssertionError(
            f"{solver_name}: invalid endpoints start={observed_path[0]} end={observed_path[-1]} expected "
            f"{start_label}->{target_label}"
        )
    if via_label not in observed_path:
        raise AssertionError(f"{solver_name}: path does not include via node '{via_label}': {observed_path}")

    adjacency: dict[str, dict[str, int]] = {label: {} for label in labels}
    for u, v, w in edges:
        lu = labels[u]
        lv = labels[v]
        prev = adjacency[lu].get(lv)
        if prev is None or int(w) < prev:
            adjacency[lu][lv] = int(w)

    total = 0
    for idx in range(len(observed_path) - 1):
        a = observed_path[idx]
        b = observed_path[idx + 1]
        weight = adjacency.get(a, {}).get(b)
        if weight is None:
            raise AssertionError(f"{solver_name}: path uses non-edge {a}->{b} in {observed_path}")
        total += int(weight)

    if total != int(observed_distance):
        raise AssertionError(
            f"{solver_name}: reported distance {observed_distance} does not match path weight {total}: {observed_path}"
        )


def run_solver(binary: Path, input_path: Path, via_label: str) -> tuple[int | None, list[str]]:
    cmd = [str(binary), str(input_path), via_label]
    completed = subprocess.run(
        cmd,
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
    return parse_solver_output((completed.stdout or "") + "\n" + (completed.stderr or ""))


def build_random_case(seed: int) -> tuple[list[str], list[tuple[int, int, int]], str, str, str]:
    rng = random.Random(seed)
    n = rng.randint(6, 24)
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
        if u == v:
            continue
        if (u, v) in edges_map:
            continue
        edges_map[(u, v)] = rng.randint(1, 20)

    start_label = labels[0]
    target_label = labels[-1]
    via_label = labels[rng.randint(1, n - 2)]
    edges = [(u, v, w) for (u, v), w in edges_map.items()]
    return labels, edges, start_label, via_label, target_label


def deterministic_no_path_cases() -> list[tuple[list[str], list[tuple[int, int, int]], str, str, str]]:
    labels = [f"v{i}" for i in range(6)]
    case1_edges = [
        (0, 1, 2),
        (1, 2, 2),
        (2, 5, 2),
        (3, 4, 1),
    ]
    case2_edges = [
        (0, 1, 3),
        (1, 2, 4),
        (2, 1, 1),
        (4, 5, 1),
    ]
    return [
        (labels, case1_edges, "v0", "v3", "v5"),
        (labels, case2_edges, "v0", "v2", "v5"),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check SP-Via correctness across available binaries.")
    parser.add_argument("--iterations", type=int, default=20, help="Number of random graph cases to test.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    iterations = max(1, int(args.iterations))

    required_binaries = [("sp_via_baseline", "baselines/via_dijkstra")]
    optional_binaries = [
        ("sp_via_chatgpt", "src/sp_via_chatgpt"),
        ("sp_via_gemini", "src/sp_via_gemini"),
    ]

    solvers: list[tuple[str, Path]] = []
    for name, rel in required_binaries:
        resolved = resolve_binary(rel)
        if not resolved:
            raise RuntimeError(f"Missing required SP-Via solver binary: {rel}")
        solvers.append((name, resolved))

    skipped: list[str] = []
    for name, rel in optional_binaries:
        resolved = resolve_binary(rel)
        if resolved:
            solvers.append((name, resolved))
        else:
            skipped.append(f"{name} ({rel})")

    cases = deterministic_no_path_cases()
    for idx in range(iterations):
        cases.append(build_random_case(seed=1337 + idx))

    with tempfile.TemporaryDirectory(prefix="sp_via_check_") as tmp:
        tmp_dir = Path(tmp)
        for case_idx, case in enumerate(cases):
            labels, edges, start_label, via_label, target_label = case
            input_path = tmp_dir / f"case_{case_idx + 1:03d}.csv"
            write_case_csv(input_path, labels, edges, start_label, target_label, via_label)

            start_idx = labels.index(start_label)
            via_idx = labels.index(via_label)
            target_idx = labels.index(target_label)
            expected_distance, _expected_path = oracle_shortest_path_via(
                labels,
                edges,
                start_idx,
                via_idx,
                target_idx,
            )

            for solver_name, solver_path in solvers:
                observed_distance, observed_path = run_solver(solver_path, input_path, via_label)
                validate_solver_answer(
                    solver_name=solver_name,
                    observed_distance=observed_distance,
                    observed_path=observed_path,
                    expected_distance=expected_distance,
                    labels=labels,
                    edges=edges,
                    start_label=start_label,
                    via_label=via_label,
                    target_label=target_label,
                )

    print(f"[check-sp-via-correctness] validated {len(cases)} cases across {len(solvers)} solver(s).")
    if skipped:
        print("[check-sp-via-correctness] skipped optional solvers:")
        for item in skipped:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
