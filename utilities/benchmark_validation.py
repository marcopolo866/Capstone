from __future__ import annotations

import csv
import heapq
import json
import re
from pathlib import Path


INF_DISTANCE = 10**18
DEFAULT_MAPPING_LIMIT = 2000


def parse_int_tokens(line: str) -> list[int]:
    return [int(item) for item in re.findall(r"-?\d+", str(line or ""))]


def parse_vf_graph(path: Path) -> list[list[int]]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise RuntimeError(f"Empty VF graph file: {path}")
    n_tokens = parse_int_tokens(lines[0])
    if not n_tokens:
        raise RuntimeError(f"Invalid VF header in {path}")
    n = max(0, int(n_tokens[0]))
    adj: list[set[int]] = [set() for _ in range(n)]
    idx = 1
    for _ in range(n):
        if idx >= len(lines):
            break
        idx += 1
    for u in range(n):
        if idx >= len(lines):
            break
        count_tokens = parse_int_tokens(lines[idx])
        idx += 1
        edge_count = int(count_tokens[0]) if count_tokens else 0
        for _ in range(max(0, edge_count)):
            if idx >= len(lines):
                break
            edge_tokens = parse_int_tokens(lines[idx])
            idx += 1
            if not edge_tokens:
                continue
            v = int(edge_tokens[1]) if len(edge_tokens) >= 2 else int(edge_tokens[0])
            if 0 <= v < n and v != u:
                adj[u].add(v)
    return [sorted(row) for row in adj]


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
        neighbors: list[int]
        unlabeled_match = len(values) >= 1 and values[0] >= 0 and len(values) == 1 + int(values[0])
        labeled_match = len(values) >= 2 and values[1] >= 0 and len(values) == 2 + int(values[1])
        if labeled_match and not unlabeled_match:
            degree = int(values[1])
            neighbors = values[2 : 2 + degree]
        elif unlabeled_match:
            degree = int(values[0])
            neighbors = values[1 : 1 + degree]
        elif len(values) >= 2:
            degree = int(values[1])
            neighbors = values[2 : 2 + max(0, degree)]
        else:
            degree = int(values[0])
            neighbors = values[1 : 1 + max(0, degree)]
        for v in neighbors:
            if 0 <= v < n and v != u:
                adj[u].add(v)
    return [sorted(row) for row in adj]


def edge_key(u: int, v: int) -> tuple[int, int] | None:
    if not isinstance(u, int) or not isinstance(v, int) or u == v:
        return None
    return (u, v) if u < v else (v, u)


def build_undirected_edge_set(adj: list[list[int]]) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for u, neighbors in enumerate(adj):
        for v in neighbors:
            ek = edge_key(u, v)
            if ek is not None:
                edges.add(ek)
    return edges


def extract_mappings_from_text(text: str, limit: int = DEFAULT_MAPPING_LIMIT) -> list[dict[int, int]]:
    src = str(text or "")
    if not src:
        return []
    out: list[dict[int, int]] = []
    seen: set[str] = set()
    max_items = max(1, int(limit))

    def add_pairs(pairs: list[tuple[str, str]]) -> None:
        if not pairs:
            return
        mapping: dict[int, int] = {}
        for p_raw, t_raw in pairs:
            try:
                p = int(p_raw)
                t = int(t_raw)
            except ValueError:
                continue
            mapping[p] = t
        if not mapping:
            return
        key = json.dumps(mapping, sort_keys=True)
        if key in seen:
            return
        seen.add(key)
        out.append(mapping)

    for raw_line in src.replace("\r", "").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        pairs1 = [(m.group(1), m.group(2)) for m in re.finditer(r"\(\s*(\d+)\s*->\s*(\d+)\s*\)", line)]
        if pairs1:
            add_pairs(pairs1)
            if len(out) >= max_items:
                break
            continue
        pairs2 = [(m.group(1), m.group(2)) for m in re.finditer(r"(\d+)\s*,\s*(\d+)\s*:", line)]
        if pairs2:
            add_pairs(pairs2)
            if len(out) >= max_items:
                break
            continue
        if re.search(r"mapping\s*[:=]", line, flags=re.IGNORECASE) or "->" in line:
            pairs3 = [(m.group(1), m.group(2)) for m in re.finditer(r"(\d+)\s*->\s*(\d+)", line)]
            if pairs3:
                add_pairs(pairs3)
                if len(out) >= max_items:
                    break
                continue
            pairs4 = [(m.group(1), m.group(2)) for m in re.finditer(r"(\d+)\s*=\s*(\d+)", line)]
            if pairs4:
                add_pairs(pairs4)
                if len(out) >= max_items:
                    break
                continue

    if not out:
        pairs = [(m.group(1), m.group(2)) for m in re.finditer(r"\(\s*(\d+)\s*->\s*(\d+)\s*\)", src)]
        if not pairs:
            pairs = [(m.group(1), m.group(2)) for m in re.finditer(r"(\d+)\s*->\s*(\d+)", src)]
        if pairs:
            add_pairs(pairs)

    return out[:max_items]


def normalize_mappings(
    mappings: list[dict[int, int]],
    pattern_n: int,
    target_n: int,
    limit: int = DEFAULT_MAPPING_LIMIT,
) -> list[dict[int, int]]:
    out: list[dict[int, int]] = []
    seen: set[str] = set()
    max_items = max(1, int(limit))
    for item in mappings:
        if not isinstance(item, dict):
            continue
        pairs: list[tuple[int, int]] = []
        for p_raw, t_raw in item.items():
            try:
                p = int(p_raw)
                t = int(t_raw)
            except (TypeError, ValueError):
                continue
            pairs.append((p, t))
        if not pairs:
            continue

        allow_p_shift = pattern_n > 0 and all(1 <= p <= pattern_n for p, _ in pairs)
        allow_t_shift = target_n > 0 and all(1 <= t <= target_n for _, t in pairs)
        variants = [(0, 0)]
        if allow_p_shift:
            variants.append((-1, 0))
        if allow_t_shift:
            variants.append((0, -1))
        if allow_p_shift and allow_t_shift:
            variants.append((-1, -1))

        best_map: dict[int, int] | None = None
        best_score = -1
        best_penalty = 10**9
        for p_shift, t_shift in variants:
            candidate: dict[int, int] = {}
            for p0, t0 in pairs:
                p = p0 + p_shift
                t = t0 + t_shift
                if p < 0 or p >= pattern_n or t < 0 or t >= target_n:
                    continue
                candidate[p] = t
            score = len(candidate)
            penalty = abs(p_shift) + abs(t_shift)
            if score > best_score or (score == best_score and penalty < best_penalty):
                best_map = candidate
                best_score = score
                best_penalty = penalty

        if not best_map:
            continue
        key = json.dumps(best_map, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(best_map)
        if len(out) >= max_items:
            break
    return out


def parse_pattern_nodes_hint(inputs: dict[str, Path | str], family: str) -> list[int] | None:
    try:
        pattern_path = Path(inputs["vf_pattern"] if family == "vf3" else inputs["lad_pattern"])
    except Exception:
        return None
    metadata_path = pattern_path.parent / "metadata.json"
    if not metadata_path.is_file():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    values = payload.get("pattern_nodes")
    if not isinstance(values, list) or not values:
        return None
    parsed: list[int] = []
    for raw in values:
        try:
            parsed.append(int(raw))
        except (TypeError, ValueError):
            return None
    return parsed


def mapping_from_pattern_nodes_hint(
    hint_nodes: list[int] | None,
    pattern_n: int,
    target_n: int,
    pattern_edges: list[tuple[int, int]],
    target_edge_set: set[tuple[int, int]],
) -> dict[int, int] | None:
    if not hint_nodes or pattern_n <= 0 or len(hint_nodes) < pattern_n:
        return None
    mapping: dict[int, int] = {}
    used: set[int] = set()
    for p in range(pattern_n):
        t = int(hint_nodes[p])
        if t < 0 or t >= target_n or t in used:
            return None
        used.add(t)
        mapping[p] = t
    for a, b in pattern_edges:
        ta = mapping.get(a)
        tb = mapping.get(b)
        if ta is None or tb is None:
            return None
        ek = edge_key(ta, tb)
        if ek is None or ek not in target_edge_set:
            return None
    return mapping


def is_valid_subgraph_mapping(pattern_adj: list[list[int]], target_adj: list[list[int]], mapping: dict[int, int]) -> bool:
    pattern_n = len(pattern_adj)
    target_n = len(target_adj)
    if pattern_n <= 0 or len(mapping) < pattern_n:
        return False
    normalized: dict[int, int] = {}
    used_targets: set[int] = set()
    for p in range(pattern_n):
        t = mapping.get(p)
        if t is None:
            return False
        t = int(t)
        if t < 0 or t >= target_n or t in used_targets:
            return False
        used_targets.add(t)
        normalized[p] = t
    target_edges = build_undirected_edge_set(target_adj)
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


def validate_subgraph_result(
    *,
    family: str,
    inputs: dict[str, Path | str],
    output_text: str,
    reported_solution_count: int | None,
    mapping_limit: int = DEFAULT_MAPPING_LIMIT,
    allow_metadata_fallback: bool = False,
) -> dict:
    if family == "vf3":
        pattern_adj = parse_vf_graph(Path(inputs["vf_pattern"]))
        target_adj = parse_vf_graph(Path(inputs["vf_target"]))
    else:
        pattern_adj = parse_lad_graph(Path(inputs["lad_pattern"]))
        target_adj = parse_lad_graph(Path(inputs["lad_target"]))

    parsed = extract_mappings_from_text(output_text, limit=mapping_limit)
    normalized = normalize_mappings(parsed, len(pattern_adj), len(target_adj), limit=mapping_limit)
    valid = [mapping for mapping in normalized if is_valid_subgraph_mapping(pattern_adj, target_adj, mapping)]
    result = {
        "family": family,
        "reported_solution_count": None if reported_solution_count is None else int(reported_solution_count),
        "parsed_mapping_count": len(parsed),
        "normalized_mapping_count": len(normalized),
        "valid_mapping_count": len(valid),
        "valid": True,
        "required_witness": bool(reported_solution_count is not None and int(reported_solution_count) > 0),
        "witness_source": "solver_output" if valid else "none",
        "error": None,
    }
    if valid:
        return result
    if not result["required_witness"]:
        return result
    if allow_metadata_fallback:
        hint_nodes = parse_pattern_nodes_hint(inputs, family)
        pattern_edges = sorted(build_undirected_edge_set(pattern_adj))
        target_edge_set = build_undirected_edge_set(target_adj)
        fallback = mapping_from_pattern_nodes_hint(
            hint_nodes,
            len(pattern_adj),
            len(target_adj),
            pattern_edges,
            target_edge_set,
        )
        if fallback is not None and is_valid_subgraph_mapping(pattern_adj, target_adj, fallback):
            result["valid_mapping_count"] = max(int(result["valid_mapping_count"]), 1)
            result["witness_source"] = "metadata_hint"
            return result
    result["valid"] = False
    result["error"] = "reported positive solution count without a valid witness mapping"
    return result


def parse_shortest_path_input(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start_label = None
    target_label = None
    via_label = None
    if lines and lines[0].lstrip().startswith("#"):
        header = lines[0].strip()
        m_start = re.search(r"start\s*=\s*([^\s#]+)", header, flags=re.IGNORECASE)
        m_target = re.search(r"target\s*=\s*([^\s#]+)", header, flags=re.IGNORECASE)
        m_via = re.search(r"via\s*=\s*([^\s#]+)", header, flags=re.IGNORECASE)
        if m_start:
            start_label = m_start.group(1).strip()
        if m_target:
            target_label = m_target.group(1).strip()
        if m_via:
            via_label = m_via.group(1).strip()

    csv_text = "\n".join(line for line in lines if not line.lstrip().startswith("#")).strip()
    edges: list[tuple[str, str, int]] = []
    labels_in_order: list[str] = []
    if csv_text:
        reader = csv.DictReader(csv_text.splitlines())
        for row in reader:
            src = str(row.get("source") or row.get("src") or "").strip()
            dst = str(row.get("target") or row.get("dst") or "").strip()
            weight_raw = str(row.get("weight") or row.get("w") or "").strip()
            if not src or not dst:
                continue
            try:
                weight = int(weight_raw)
            except (TypeError, ValueError):
                continue
            edges.append((src, dst, int(weight)))
            labels_in_order.append(src)
            labels_in_order.append(dst)

    unique_labels: list[str] = []
    seen: set[str] = set()
    for label in labels_in_order:
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_labels.append(label)

    for label in (start_label, target_label, via_label):
        if label and label.lower() not in seen:
            unique_labels.append(label)
            seen.add(label.lower())

    if unique_labels:
        if not start_label:
            start_label = unique_labels[0]
        if not target_label:
            target_label = unique_labels[-1]

    return {
        "labels": unique_labels,
        "edges": edges,
        "start_label": start_label,
        "target_label": target_label,
        "via_label": via_label,
    }


def extract_path_tokens(output_text: str) -> list[str]:
    lines = [line.strip() for line in str(output_text or "").replace("\r", "").split("\n") if line.strip()]
    for line in reversed(lines):
        if re.match(r"(?i)^runtime\s*:", line) or re.search(r"(?i)\bdistance\s*[:=]", line) or re.fullmatch(r"[+-]?\d+", line):
            continue
        raw = line.split(";", 1)[0].strip()
        parts = [part.strip() for part in raw.replace("->", ",").split(",") if part.strip()]
        if len(parts) >= 2:
            return parts
    return []


def dijkstra(adj: list[list[tuple[int, int]]], start: int) -> tuple[list[int], list[int]]:
    n = len(adj)
    dist = [INF_DISTANCE] * n
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


def shortest_path_oracle(path: Path) -> tuple[int | None, str | None]:
    parsed = parse_shortest_path_input(path)
    labels = list(parsed["labels"])
    label_to_idx = {label: idx for idx, label in enumerate(labels)}
    start_label = parsed["start_label"]
    target_label = parsed["target_label"]
    via_label = parsed["via_label"]
    if not labels or not start_label or not target_label:
        return None, via_label

    adjacency: list[list[tuple[int, int]]] = [[] for _ in range(len(labels))]
    for src, dst, weight in parsed["edges"]:
        u = label_to_idx.get(src)
        v = label_to_idx.get(dst)
        if u is None or v is None:
            continue
        adjacency[u].append((v, int(weight)))

    start_idx = label_to_idx.get(start_label)
    target_idx = label_to_idx.get(target_label)
    if start_idx is None or target_idx is None:
        return None, via_label

    if via_label:
        via_idx = label_to_idx.get(via_label)
        if via_idx is None:
            return None, via_label
        dist_a, _ = dijkstra(adjacency, start_idx)
        dist_b, _ = dijkstra(adjacency, via_idx)
        if dist_a[via_idx] >= INF_DISTANCE or dist_b[target_idx] >= INF_DISTANCE:
            return None, via_label
        return int(dist_a[via_idx] + dist_b[target_idx]), via_label

    dist, _ = dijkstra(adjacency, start_idx)
    if dist[target_idx] >= INF_DISTANCE:
        return None, via_label
    return int(dist[target_idx]), via_label


def validate_shortest_path_result(
    *,
    input_path: Path,
    reported_distance: str | None,
    path_tokens: list[str],
) -> dict:
    parsed = parse_shortest_path_input(input_path)
    labels = list(parsed["labels"])
    label_to_idx = {label: idx for idx, label in enumerate(labels)}
    start_label = parsed["start_label"]
    target_label = parsed["target_label"]
    via_label = parsed["via_label"]
    adjacency: dict[str, dict[str, int]] = {label: {} for label in labels}
    for src, dst, weight in parsed["edges"]:
        previous = adjacency.get(src, {}).get(dst)
        if previous is None or int(weight) < previous:
            adjacency.setdefault(src, {})[dst] = int(weight)

    oracle_distance, _ = shortest_path_oracle(input_path)
    result = {
        "oracle_distance": None if oracle_distance is None else str(oracle_distance),
        "reported_distance": reported_distance,
        "path_length": max(0, len(path_tokens) - 1) if path_tokens else None,
        "path_present": bool(path_tokens),
        "path_valid": True,
        "distance_valid": True,
        "valid": True,
        "error": None,
    }

    if reported_distance == "INF":
        if oracle_distance is not None:
            result["distance_valid"] = False
            result["valid"] = False
            result["error"] = f"reported unreachable but oracle distance is {oracle_distance}"
        return result

    if reported_distance is None:
        result["distance_valid"] = False
        result["valid"] = False
        result["error"] = "missing reported distance"
        return result

    try:
        numeric_distance = int(str(reported_distance))
    except (TypeError, ValueError):
        result["distance_valid"] = False
        result["valid"] = False
        result["error"] = f"invalid reported distance: {reported_distance}"
        return result

    if oracle_distance is None or numeric_distance != int(oracle_distance):
        result["distance_valid"] = False
        result["valid"] = False
        result["error"] = (
            f"reported distance {numeric_distance} does not match oracle "
            f"{'INF' if oracle_distance is None else oracle_distance}"
        )
        return result

    if not path_tokens:
        return result

    if not start_label or not target_label:
        result["path_valid"] = False
        result["valid"] = False
        result["error"] = "missing start/target labels in input"
        return result
    if path_tokens[0] != start_label or path_tokens[-1] != target_label:
        result["path_valid"] = False
        result["valid"] = False
        result["error"] = f"path endpoints {path_tokens[0]}->{path_tokens[-1]} do not match {start_label}->{target_label}"
        return result
    if via_label and via_label not in path_tokens:
        result["path_valid"] = False
        result["valid"] = False
        result["error"] = f"path does not include required via node {via_label}"
        return result

    total_weight = 0
    for idx in range(len(path_tokens) - 1):
        src = path_tokens[idx]
        dst = path_tokens[idx + 1]
        weight = adjacency.get(src, {}).get(dst)
        if weight is None:
            result["path_valid"] = False
            result["valid"] = False
            result["error"] = f"path uses non-edge {src}->{dst}"
            return result
        total_weight += int(weight)

    if total_weight != numeric_distance:
        result["path_valid"] = False
        result["valid"] = False
        result["error"] = f"path weight {total_weight} does not match reported distance {numeric_distance}"
        return result

    return result
