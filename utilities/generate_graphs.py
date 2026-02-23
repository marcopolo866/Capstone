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


def build_undirected_adj(adj: list[list[int]]) -> list[list[int]]:
    undirected = [set(neigh) for neigh in adj]
    for u, neighbors in enumerate(adj):
        for v in neighbors:
            if v < 0 or v >= len(adj) or v == u:
                continue
            undirected[u].add(v)
            undirected[v].add(u)
    return [sorted(list(s)) for s in undirected]


def pick_connected_nodes(undirected_adj: list[list[int]], k: int, rng: random.Random) -> list[int]:
    n = len(undirected_adj)
    if k <= 0 or k > n:
        raise ValueError("k must be between 1 and N")

    remaining = set(range(n))
    component = None
    while remaining:
        start = rng.choice(tuple(remaining))
        queue = [start]
        comp = []
        seen = {start}
        while queue:
            u = queue.pop()
            comp.append(u)
            for v in undirected_adj[u]:
                if v not in seen:
                    seen.add(v)
                    queue.append(v)
        remaining.difference_update(seen)
        if len(comp) >= k:
            component = comp
            break

    if component is None:
        raise ValueError("No connected component is large enough for the chosen k")

    start = rng.choice(component)
    selected = {start}
    frontier = set(undirected_adj[start]) - selected
    while len(selected) < k:
        if not frontier:
            raise ValueError("Failed to build a connected pattern of size k")
        nxt = rng.choice(tuple(frontier))
        frontier.discard(nxt)
        if nxt in selected:
            continue
        selected.add(nxt)
        for v in undirected_adj[nxt]:
            if v not in selected:
                frontier.add(v)
    return list(selected)


def write_lad(path: Path, adj: list[list[int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for neighbors in adj:
            line = f"{len(neighbors)}"
            if neighbors:
                line += " " + " ".join(str(v) for v in neighbors)
            fh.write(line + "\n")


def write_vertex_labelled_lad(path: Path, adj: list[list[int]], labels: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(adj)}\n")
        for i, neighbors in enumerate(adj):
            line = f"{labels[i]} {len(neighbors)}"
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
    if algorithm not in {"dijkstra", "glasgow", "vf3", "subgraph"}:
        raise ValueError("Unknown algorithm for generation")

    n = parse_int(args.n, "N", minimum=2)
    k = None
    if algorithm in {"glasgow", "vf3", "subgraph"}:
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

    pattern_nodes = None
    if algorithm == "dijkstra":
        labels = [f"v{i}" for i in range(n)]
        edges = generate_directed_edges(n, rng, density)
        path = out_dir / "dijkstra_generated.csv"
        write_dijkstra_csv(path, edges, labels)
        generated.append(path)
    else:
        labels = None
        target_adj = generate_adjacency(n, rng, density)
        undirected_adj = build_undirected_adj(target_adj)
        if algorithm in {"glasgow", "vf3", "subgraph"}:
            target_adj = undirected_adj
        nodes = pick_connected_nodes(undirected_adj, k, rng)
        pattern_nodes = list(nodes)
        ensure_pattern_edges(target_adj, nodes, rng)
        node_set = set(nodes)
        pattern_map = {node: idx for idx, node in enumerate(nodes)}
        pattern_adj = []
        for node in nodes:
            neighbors = [pattern_map[v] for v in target_adj[node] if v in node_set]
            pattern_adj.append(sorted(neighbors))

        if algorithm in {"vf3", "subgraph"}:
            labels = [i % 4 for i in range(n)]

        if algorithm in {"glasgow", "subgraph"}:
            target_path = out_dir / "glasgow_target.lad"
            pattern_path = out_dir / "glasgow_pattern.lad"
            if labels is None:
                write_lad(target_path, target_adj)
                write_lad(pattern_path, pattern_adj)
            else:
                pattern_labels = [labels[node] for node in nodes]
                write_vertex_labelled_lad(target_path, target_adj, labels)
                write_vertex_labelled_lad(pattern_path, pattern_adj, pattern_labels)
            generated.extend([pattern_path, target_path])

        if algorithm in {"vf3", "subgraph"}:
            if labels is None:
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
    if pattern_nodes is not None:
        metadata["pattern_nodes"] = [int(x) for x in pattern_nodes]
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print(",".join(p.as_posix() for p in generated))


if __name__ == "__main__":
    main()
