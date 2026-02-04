import argparse
import csv
import json
import random
import time
from pathlib import Path


def parse_int(value: str, name: str, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def generate_directed_edges(n: int, rng: random.Random, density: float) -> list[tuple[int, int, int]]:
    edges: dict[tuple[int, int], int] = {}
    for i in range(n - 1):
        edges[(i, i + 1)] = rng.randint(1, 20)
    max_edges = n * (n - 1)
    target_edges = max(n - 1, min(max_edges, int(round(density * max_edges))))
    attempts = 0
    while len(edges) < target_edges and attempts < target_edges * 10:
        u = rng.randrange(n)
        v = rng.randrange(n)
        if u == v:
            attempts += 1
            continue
        if u in (0, n - 1) or v in (0, n - 1):
            attempts += 1
            continue
        if (u, v) not in edges:
            edges[(u, v)] = rng.randint(1, 20)
        attempts += 1
    return [(u, v, w) for (u, v), w in edges.items()]


def write_dijkstra_csv(path: Path, edges: list[tuple[int, int, int]], labels: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(f"# start={labels[0]} target={labels[-1]}\n")
        writer = csv.writer(fh)
        writer.writerow(["source", "target", "weight"])
        for u, v, w in edges:
            writer.writerow([labels[u], labels[v], w])


def generate_adjacency(n: int, rng: random.Random, density: float) -> list[list[int]]:
    adj = [set() for _ in range(n)]
    for i in range(n - 1):
        adj[i].add(i + 1)
    max_edges = n * (n - 1)
    target_edges = max(n - 1, min(max_edges, int(round(density * max_edges))))
    attempts = 0
    while sum(len(s) for s in adj) < target_edges and attempts < target_edges * 10:
        u = rng.randrange(n)
        v = rng.randrange(n)
        if u == v:
            attempts += 1
            continue
        adj[u].add(v)
        attempts += 1
    return [sorted(list(s)) for s in adj]


def ensure_pattern_edges(target_adj: list[list[int]], nodes: list[int], rng: random.Random) -> None:
    if len(nodes) < 2:
        return
    node_set = set(nodes)
    for u in nodes:
        if any(v in node_set for v in target_adj[u]):
            return
    u, v = nodes[0], nodes[1]
    if v not in target_adj[u]:
        target_adj[u].append(v)
        target_adj[u] = sorted(target_adj[u])


def write_lad(path: Path, adj: list[list[int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for neighbors in adj:
            line = f"{len(neighbors)}"
            if neighbors:
                line += " " + " ".join(str(v) for v in neighbors)
            fh.write(line + "\n")


def write_grf(path: Path, adj: list[list[int]], labels: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for i, label in enumerate(labels):
            fh.write(f"{i} {label}\n")
        for i, neighbors in enumerate(adj):
            fh.write(f"{len(neighbors)}\n")
            for v in neighbors:
                fh.write(f"{i} {v}\n")


def write_vf(path: Path, adj: list[list[int]], labels: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for i, label in enumerate(labels):
            fh.write(f"{i} {label}\n")
        for i, neighbors in enumerate(adj):
            fh.write(f"{len(neighbors)}\n")
            for v in neighbors:
                fh.write(f"{i} {v}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--n", required=True)
    parser.add_argument("--k", default="")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--density", default="0.05")
    parser.add_argument("--seed", default="")
    args = parser.parse_args()

    algorithm = args.algorithm.strip().lower()
    if algorithm not in {"dijkstra", "glasgow", "vf3"}:
        raise ValueError("Unknown algorithm for generation")

    n = parse_int(args.n, "N", minimum=2)
    k = None
    if algorithm in {"glasgow", "vf3"}:
        if args.k is None or str(args.k).strip() == "":
            raise ValueError("k is required for subgraph generation")
        k = parse_int(args.k, "k", minimum=1)
        if k >= n:
            raise ValueError("k must be smaller than N")

    try:
        density = float(args.density)
    except (TypeError, ValueError):
        raise ValueError("density must be a number between 0 and 1")
    if density <= 0 or density > 1:
        raise ValueError("density must be in the range (0, 1]")

    seed = int(args.seed) if str(args.seed).strip() else int(time.time() * 1000) & 0xFFFFFFFF
    rng = random.Random(seed)
    out_dir = Path(args.out_dir)

    generated = []

    if algorithm == "dijkstra":
        labels = [f"v{i}" for i in range(n)]
        edges = generate_directed_edges(n, rng, density)
        path = out_dir / "dijkstra_generated.csv"
        write_dijkstra_csv(path, edges, labels)
        generated.append(path)
    else:
        target_adj = generate_adjacency(n, rng, density)
        nodes = rng.sample(range(n), k)
        ensure_pattern_edges(target_adj, nodes, rng)
        node_set = set(nodes)
        pattern_map = {node: idx for idx, node in enumerate(nodes)}
        pattern_adj = []
        for node in nodes:
            neighbors = [pattern_map[v] for v in target_adj[node] if v in node_set]
            pattern_adj.append(sorted(neighbors))

        if algorithm == "glasgow":
            target_path = out_dir / "glasgow_target.lad"
            pattern_path = out_dir / "glasgow_pattern.lad"
            write_lad(target_path, target_adj)
            write_lad(pattern_path, pattern_adj)
        else:
            labels = [i % 4 for i in range(n)]
            pattern_labels = [labels[node] for node in nodes]
            target_path = out_dir / "vf3_target.vf"
            pattern_path = out_dir / "vf3_pattern.vf"
            write_vf(target_path, target_adj, labels)
            write_vf(pattern_path, pattern_adj, pattern_labels)

        generated.extend([pattern_path, target_path])

    metadata = {
        "algorithm": algorithm,
        "n": n,
        "k": k,
        "density": density,
        "seed": seed,
        "files": [p.as_posix() for p in generated],
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print(",".join(p.as_posix() for p in generated))


if __name__ == "__main__":
    main()
