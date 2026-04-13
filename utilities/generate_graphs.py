"""Generate benchmark input graphs for the supported algorithm families."""

# - This file is the single source of truth for synthetic input generation used
#   by the desktop app, headless CLI, CI runner, and generator CLI tests.
# - If graph-family semantics change here, keep docs and every caller's seed /
#   parameter handling aligned so benchmark manifests stay interpretable.

import argparse
import csv
import json
import random
import time
from pathlib import Path


GRAPH_FAMILIES = ("random_density", "erdos_renyi", "barabasi_albert", "grid")


def parse_int(value: str, name: str, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def normalize_graph_family(value: str | None) -> str:
    token = str(value or "random_density").strip().lower().replace("-", "_")
    aliases = {
        "random": "random_density",
        "density": "random_density",
        "random_density": "random_density",
        "erdos_renyi": "erdos_renyi",
        "er": "erdos_renyi",
        "ba": "barabasi_albert",
        "barabasi_albert": "barabasi_albert",
        "grid": "grid",
    }
    family = aliases.get(token, token)
    if family not in GRAPH_FAMILIES:
        raise ValueError(f"graph family must be one of: {', '.join(GRAPH_FAMILIES)}")
    return family


def _target_edge_budget(n: int, density: float, *, directed: bool) -> int:
    max_edges = n * (n - 1) if directed else (n * (n - 1)) // 2
    return max(0, min(max_edges, int(round(float(density) * float(max_edges)))))


def _adj_sets_to_lists(adj_sets: list[set[int]]) -> list[list[int]]:
    return [sorted(list(row)) for row in adj_sets]


def _count_undirected_edges(adj: list[list[int]]) -> int:
    total = 0
    for u, neighbors in enumerate(adj):
        for v in neighbors:
            if v > u:
                total += 1
    return total


def _add_random_directed_edges(
    edges: dict[tuple[int, int], int],
    *,
    n: int,
    rng: random.Random,
    target_edges: int,
    attempts_multiplier: int = 12,
) -> None:
    attempts = 0
    max_attempts = max(1, target_edges * attempts_multiplier)
    while len(edges) < target_edges and attempts < max_attempts:
        u = rng.randrange(n)
        v = rng.randrange(n)
        attempts += 1
        if u == v or (u, v) in edges:
            continue
        edges[(u, v)] = rng.randint(1, 20)


def _add_random_undirected_edges(
    adj_sets: list[set[int]],
    *,
    rng: random.Random,
    target_edges: int,
    attempts_multiplier: int = 12,
) -> None:
    n = len(adj_sets)
    attempts = 0
    max_attempts = max(1, target_edges * attempts_multiplier)
    while _count_undirected_edges(_adj_sets_to_lists(adj_sets)) < target_edges and attempts < max_attempts:
        u = rng.randrange(n)
        v = rng.randrange(n)
        attempts += 1
        if u == v or v in adj_sets[u]:
            continue
        adj_sets[u].add(v)
        adj_sets[v].add(u)


def _generate_random_density_directed_edges(n: int, rng: random.Random, density: float) -> list[tuple[int, int, int]]:
    edges: dict[tuple[int, int], int] = {}
    for i in range(n - 1):
        edges[(i, i + 1)] = rng.randint(1, 20)
    target_edges = max(n - 1, _target_edge_budget(n, density, directed=True))
    _add_random_directed_edges(edges, n=n, rng=rng, target_edges=target_edges)
    return [(u, v, w) for (u, v), w in edges.items()]


def _generate_erdos_renyi_directed_edges(n: int, rng: random.Random, density: float) -> list[tuple[int, int, int]]:
    edges: dict[tuple[int, int], int] = {}
    for i in range(n - 1):
        edges[(i, i + 1)] = rng.randint(1, 20)
    for u in range(n):
        for v in range(n):
            if u == v or (u, v) in edges:
                continue
            if rng.random() <= density:
                edges[(u, v)] = rng.randint(1, 20)
    return [(u, v, w) for (u, v), w in edges.items()]


def _generate_barabasi_albert_undirected(n: int, rng: random.Random, density: float) -> list[list[int]]:
    if n <= 1:
        return [[] for _ in range(n)]
    m = max(1, min(n - 1, int(round(float(density) * float(max(2, n - 1)) / 2.0))))
    seed_size = min(n, max(2, m + 1))
    adj_sets = [set() for _ in range(n)]
    repeated_nodes: list[int] = []
    for u in range(seed_size):
        for v in range(u + 1, seed_size):
            adj_sets[u].add(v)
            adj_sets[v].add(u)
    for node in range(seed_size):
        repeated_nodes.extend([node] * len(adj_sets[node]))
    if not repeated_nodes:
        repeated_nodes = list(range(seed_size))
    for new_node in range(seed_size, n):
        targets: set[int] = set()
        while len(targets) < min(m, new_node):
            targets.add(rng.choice(repeated_nodes))
        for target in targets:
            adj_sets[new_node].add(target)
            adj_sets[target].add(new_node)
        repeated_nodes.extend(list(targets))
        repeated_nodes.extend([new_node] * len(targets))
    return _adj_sets_to_lists(adj_sets)


def _grid_shape(n: int) -> tuple[int, int]:
    rows = max(1, int(round(n ** 0.5)))
    cols = max(1, (n + rows - 1) // rows)
    while rows * cols < n:
        rows += 1
    return rows, cols


def _generate_grid_undirected(n: int) -> list[list[int]]:
    rows, cols = _grid_shape(n)
    adj_sets = [set() for _ in range(n)]
    for node in range(n):
        r, c = divmod(node, cols)
        for nr, nc in ((r + 1, c), (r, c + 1)):
            neighbor = nr * cols + nc
            if neighbor < n:
                adj_sets[node].add(neighbor)
                adj_sets[neighbor].add(node)
    return _adj_sets_to_lists(adj_sets)


def _directed_edges_from_undirected(
    undirected_adj: list[list[int]],
    *,
    rng: random.Random,
    density: float,
) -> list[tuple[int, int, int]]:
    n = len(undirected_adj)
    edges: dict[tuple[int, int], int] = {}
    for i in range(max(0, n - 1)):
        edges[(i, i + 1)] = rng.randint(1, 20)
    for u, neighbors in enumerate(undirected_adj):
        for v in neighbors:
            if v <= u:
                continue
            mode = rng.random()
            if mode < 0.34:
                edges.setdefault((u, v), rng.randint(1, 20))
            elif mode < 0.68:
                edges.setdefault((v, u), rng.randint(1, 20))
            else:
                edges.setdefault((u, v), rng.randint(1, 20))
                edges.setdefault((v, u), rng.randint(1, 20))
    target_edges = max(n - 1, _target_edge_budget(n, density, directed=True))
    _add_random_directed_edges(edges, n=n, rng=rng, target_edges=target_edges)
    return [(u, v, w) for (u, v), w in edges.items()]


def generate_directed_edges(
    n: int,
    rng: random.Random,
    density: float,
    graph_family: str = "random_density",
) -> list[tuple[int, int, int]]:
    family = normalize_graph_family(graph_family)
    if family == "random_density":
        return _generate_random_density_directed_edges(n, rng, density)
    if family == "erdos_renyi":
        return _generate_erdos_renyi_directed_edges(n, rng, density)
    if family == "barabasi_albert":
        return _directed_edges_from_undirected(
            _generate_barabasi_albert_undirected(n, rng, density),
            rng=rng,
            density=density,
        )
    return _directed_edges_from_undirected(_generate_grid_undirected(n), rng=rng, density=density)


def write_dijkstra_csv(
    path: Path,
    edges: list[tuple[int, int, int]],
    labels: list[str],
    *,
    via_label: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        header = f"# start={labels[0]} target={labels[-1]}"
        if via_label:
            header += f" via={via_label}"
        fh.write(header + "\n")
        writer = csv.writer(fh)
        writer.writerow(["source", "target", "weight"])
        for u, v, w in edges:
            writer.writerow([labels[u], labels[v], w])


def generate_adjacency(
    n: int,
    rng: random.Random,
    density: float,
    graph_family: str = "random_density",
) -> list[list[int]]:
    family = normalize_graph_family(graph_family)
    if family == "random_density":
        adj_sets = [set() for _ in range(n)]
        for i in range(n - 1):
            adj_sets[i].add(i + 1)
            adj_sets[i + 1].add(i)
        target_edges = max(n - 1, _target_edge_budget(n, density, directed=False))
        _add_random_undirected_edges(adj_sets, rng=rng, target_edges=target_edges)
        return _adj_sets_to_lists(adj_sets)
    if family == "erdos_renyi":
        adj_sets = [set() for _ in range(n)]
        for i in range(n - 1):
            adj_sets[i].add(i + 1)
            adj_sets[i + 1].add(i)
        for u in range(n):
            for v in range(u + 1, n):
                if v in adj_sets[u]:
                    continue
                if rng.random() <= density:
                    adj_sets[u].add(v)
                    adj_sets[v].add(u)
        return _adj_sets_to_lists(adj_sets)
    if family == "barabasi_albert":
        return _generate_barabasi_albert_undirected(n, rng, density)
    adj = _generate_grid_undirected(n)
    adj_sets = [set(row) for row in adj]
    target_edges = max(_count_undirected_edges(adj), _target_edge_budget(n, density, directed=False))
    _add_random_undirected_edges(adj_sets, rng=rng, target_edges=target_edges)
    return _adj_sets_to_lists(adj_sets)


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


def sanitize_undirected_simple_adj(adj: list[list[int]]) -> list[list[int]]:
    n = len(adj)
    cleaned = [set() for _ in range(n)]
    for u, neighbors in enumerate(adj):
        for raw_v in neighbors:
            try:
                v = int(raw_v)
            except (TypeError, ValueError):
                continue
            if v < 0 or v >= n or v == u:
                continue
            cleaned[u].add(v)
            cleaned[v].add(u)
    return [sorted(list(s)) for s in cleaned]


def assert_undirected_simple_adj(adj: list[list[int]], name: str) -> None:
    n = len(adj)
    for u, neighbors in enumerate(adj):
        seen = set()
        for v in neighbors:
            if not isinstance(v, int):
                raise ValueError(f"{name}: non-integer endpoint at node {u}")
            if v < 0 or v >= n:
                raise ValueError(f"{name}: out-of-range endpoint ({u}, {v})")
            if v == u:
                raise ValueError(f"{name}: self-loop at node {u}")
            if v in seen:
                raise ValueError(f"{name}: duplicate edge endpoint {u}->{v}")
            seen.add(v)
    for u, neighbors in enumerate(adj):
        for v in neighbors:
            if u not in adj[v]:
                raise ValueError(f"{name}: asymmetric adjacency between {u} and {v}")


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
    parser.add_argument("--graph-family", default="random_density")
    parser.add_argument("--seed", default="")
    args = parser.parse_args()

    algorithm = args.algorithm.strip().lower()
    if algorithm not in {"dijkstra", "sp_via", "glasgow", "vf3", "subgraph"}:
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
    graph_family = normalize_graph_family(args.graph_family)

    seed = int(args.seed) if str(args.seed).strip() else int(time.time() * 1000) & 0xFFFFFFFF
    rng = random.Random(seed)
    out_dir = Path(args.out_dir)

    generated = []

    pattern_nodes = None
    metadata_via_label: str | None = None
    if algorithm in {"dijkstra", "sp_via"}:
        labels = [f"v{i}" for i in range(n)]
        edges = generate_directed_edges(n, rng, density, graph_family=graph_family)
        via_label = None
        if algorithm == "sp_via":
            via_index = max(0, min(n - 1, n // 2))
            if n > 2 and via_index in {0, n - 1}:
                via_index = 1
            via_label = labels[via_index]
        path = out_dir / ("sp_via_generated.csv" if algorithm == "sp_via" else "dijkstra_generated.csv")
        write_dijkstra_csv(path, edges, labels, via_label=via_label)
        generated.append(path)
        metadata_via_label = via_label
    else:
        labels = None
        target_adj = generate_adjacency(n, rng, density, graph_family=graph_family)
        undirected_adj = sanitize_undirected_simple_adj(build_undirected_adj(target_adj))
        assert_undirected_simple_adj(undirected_adj, "target_adj")
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
        pattern_adj = sanitize_undirected_simple_adj(pattern_adj)
        assert_undirected_simple_adj(pattern_adj, "pattern_adj")

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
        "graph_family": graph_family,
        "n": n,
        "k": k,
        "density": density,
        "seed": seed,
        "files": [p.as_posix() for p in generated],
    }
    if algorithm in {"dijkstra", "sp_via"}:
        max_edges = n * (n - 1)
        metadata["actual_density"] = 0.0 if max_edges <= 0 else float(len(edges)) / float(max_edges)
    else:
        max_edges = (n * (n - 1)) // 2
        actual_edges = _count_undirected_edges(undirected_adj)
        metadata["actual_density"] = 0.0 if max_edges <= 0 else float(actual_edges) / float(max_edges)
    if algorithm == "sp_via":
        if metadata_via_label:
            metadata["via"] = metadata_via_label
    if pattern_nodes is not None:
        metadata["pattern_nodes"] = [int(x) for x in pattern_nodes]
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print(",".join(p.as_posix() for p in generated))


if __name__ == "__main__":
    main()
