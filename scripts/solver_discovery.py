#!/usr/bin/env python3
"""Discover solver variants from src/[PROBLEM][LLM][FILETYPE].cpp names."""

# - Discovery is a contract for build scripts, CI, and the UI; changes to ids,
#   family bucketing, or labels ripple across the whole repository.
# - Baseline rows are injected here so downstream tools can treat discovered and
#   baseline variants through the same catalog shape.

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


FILE_RE = re.compile(r"^\[(?P<problem>[^\]]+)\]\[(?P<llm>[^\]]+)\]\[(?P<filetype>[^\]]+)\]\.cpp$")

PROBLEM_FILETYPE_TO_FAMILY = {
    ("shortestpath", "csv"): ("dijkstra", "dijkstra", "Dijkstra"),
    ("shortestpathvia", "csv"): ("sp_via", "sp_via", "With Intermediate"),
    ("subgraphisomorphism", "grf"): ("vf3", "vf3", "VF3"),
    ("subgraphisomorphism", "lad"): ("glasgow", "glasgow", "Glasgow"),
}

BASELINES = [
    {
        "variant_id": "dijkstra_baseline",
        "family": "dijkstra",
        "algorithm": "dijkstra",
        "label": "Dijkstra Baseline",
        "binary_path": "baselines/dijkstra",
        "role": "baseline",
        "llm_key": None,
        "llm_label": None,
    },
    {
        "variant_id": "sp_via_baseline",
        "family": "sp_via",
        "algorithm": "sp_via",
        "label": "With Intermediate Baseline",
        "binary_path": "baselines/via_dijkstra",
        "role": "baseline",
        "llm_key": None,
        "llm_label": None,
    },
    {
        "variant_id": "vf3_baseline",
        "family": "vf3",
        "algorithm": "vf3",
        "label": "VF3 Baseline",
        "binary_path": "baselines/vf3lib/bin/vf3",
        "role": "baseline",
        "llm_key": None,
        "llm_label": None,
    },
    {
        "variant_id": "glasgow_baseline",
        "family": "glasgow",
        "algorithm": "glasgow",
        "label": "Glasgow Baseline",
        "binary_path": "baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver",
        "role": "baseline",
        "llm_key": None,
        "llm_label": None,
    },
]


def slugify_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").lower()
    return token or "unknown"


def title_case_token(value: str) -> str:
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", value.strip()) if p]
    if not parts:
        return "Unknown"
    return " ".join(part[:1].upper() + part[1:].lower() for part in parts)


def family_export_name(family: str) -> str:
    if family == "vf3":
        return "Vf3"
    parts = [part for part in str(family or "").split("_") if part]
    if not parts:
        return "Unknown"
    return "".join(part[:1].upper() + part[1:] for part in parts)


@dataclass(frozen=True)
class SolverVariant:
    variant_id: str
    family: str
    family_label: str
    algorithm: str
    source_path: str
    binary_path: str
    llm_key: str
    llm_label: str
    role: str
    label: str
    wasm_module_id: str
    wasm_script_path: str
    wasm_wasm_path: str
    wasm_factory_name: str


def discover_variants(repo_root: Path) -> list[SolverVariant]:
    src_dir = repo_root / "src"
    found: list[SolverVariant] = []
    if not src_dir.is_dir():
        return found

    for path in sorted(src_dir.glob("*.cpp")):
        match = FILE_RE.match(path.name)
        if not match:
            continue
        problem = slugify_token(match.group("problem"))
        llm_raw = match.group("llm")
        llm_key = slugify_token(llm_raw)
        filetype = slugify_token(match.group("filetype"))
        mapping = PROBLEM_FILETYPE_TO_FAMILY.get((problem, filetype))
        if mapping is None:
            continue
        family, algorithm, family_label = mapping
        variant_id = f"{family}_{llm_key}"
        llm_label = title_case_token(llm_raw)
        export = f"create{family_export_name(family)}{''.join(part[:1].upper() + part[1:].lower() for part in llm_key.split('_'))}Module"
        found.append(
            SolverVariant(
                variant_id=variant_id,
                family=family,
                family_label=family_label,
                algorithm=algorithm,
                source_path=str(path.relative_to(repo_root).as_posix()),
                binary_path=f"src/{variant_id}",
                llm_key=llm_key,
                llm_label=llm_label,
                role="variant",
                label=f"{family_label} {llm_label}",
                wasm_module_id=variant_id,
                wasm_script_path=f"wasm/{variant_id}.js",
                wasm_wasm_path=f"wasm/{variant_id}.wasm",
                wasm_factory_name=export,
            )
        )

    return found


def build_catalog(repo_root: Path) -> dict:
    variants = discover_variants(repo_root)
    families: dict[str, dict] = {}
    for item in variants:
        families.setdefault(
            item.family,
            {
                "family": item.family,
                "family_label": item.family_label,
                "algorithm": item.algorithm,
                "variants": [],
            },
        )["variants"].append(asdict(item))

    for family in families.values():
        family["variants"].sort(key=lambda row: (row["llm_label"].lower(), row["variant_id"]))

    all_solver_rows = []
    all_solver_rows.extend(BASELINES)
    all_solver_rows.extend(
        {
            "variant_id": v.variant_id,
            "family": v.family,
            "algorithm": v.algorithm,
            "label": v.label,
            "binary_path": v.binary_path,
            "role": v.role,
            "llm_key": v.llm_key,
            "llm_label": v.llm_label,
        }
        for v in variants
    )

    by_algorithm: dict[str, list[dict]] = {"dijkstra": [], "sp_via": [], "vf3": [], "glasgow": [], "subgraph": []}
    for row in all_solver_rows:
        algo = str(row.get("algorithm") or "").strip().lower()
        if algo in by_algorithm:
            by_algorithm[algo].append(dict(row))
        if algo in ("vf3", "glasgow"):
            by_algorithm["subgraph"].append(dict(row))

    for key in by_algorithm:
        by_algorithm[key].sort(key=lambda row: (row["family"], row["role"] != "baseline", row["label"].lower()))

    return {
        "schema_version": 1,
        "source_pattern": "[PROBLEM][LLM][FILETYPE].cpp",
        "families": sorted(families.values(), key=lambda row: row["family"]),
        "variants": [asdict(v) for v in variants],
        "baselines": BASELINES,
        "solvers": all_solver_rows,
        "by_algorithm": by_algorithm,
    }


def iter_binary_paths(catalog: dict, include_baselines: bool = True) -> Iterable[str]:
    if include_baselines:
        for row in catalog.get("baselines", []):
            path = str(row.get("binary_path") or "").strip()
            if path:
                yield path
    for row in catalog.get("variants", []):
        path = str(row.get("binary_path") or "").strip()
        if path:
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover solver variants from src file names.")
    parser.add_argument("--repo-root", default="", help="Optional repository root override.")
    parser.add_argument("--write-json", default="", help="Write catalog JSON to this path.")
    parser.add_argument("--print-binaries", action="store_true", help="Print one expected binary path per line.")
    parser.add_argument("--exclude-baselines", action="store_true", help="Exclude baselines from --print-binaries.")
    args = parser.parse_args()

    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = Path(__file__).resolve().parent.parent

    catalog = build_catalog(repo_root)

    if args.write_json:
        out_path = Path(args.write_json)
        if not out_path.is_absolute():
            out_path = repo_root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    if args.print_binaries:
        for path in iter_binary_paths(catalog, include_baselines=not args.exclude_baselines):
            print(path)
        return 0

    print(json.dumps(catalog, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
