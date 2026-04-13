from __future__ import annotations

import csv
import heapq
import re
from pathlib import Path


INF_DISTANCE = 10**18


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
