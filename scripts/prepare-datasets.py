#!/usr/bin/env python3
"""Download and convert desktop-runner datasets into runnable local formats."""

# - This is a CLI shim over desktop_runner.app dataset helpers so dataset
#   preparation rules live in one place for GUI and scripted workflows.
# - Keep output paths and progress messaging aligned with the desktop runner to
#   avoid confusing users about where prepared datasets should appear.

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from desktop_runner.app import dataset_dir_for_spec, format_bytes_human, load_dataset_catalog, prepare_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare datasets declared in desktop_runner/datasets_catalog.json.")
    parser.add_argument("--list", action="store_true", help="List available dataset ids and exit.")
    parser.add_argument("--all", action="store_true", help="Prepare all datasets.")
    parser.add_argument(
        "--id",
        dest="dataset_ids",
        action="append",
        default=[],
        help="Dataset id to prepare (repeatable).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = load_dataset_catalog()
    by_id = {spec.dataset_id: spec for spec in catalog}

    if args.list:
        for spec in catalog:
            print(f"{spec.dataset_id}\t{spec.tab_id}\t{spec.name}")
        return 0

    selected_ids: list[str]
    if args.all:
        selected_ids = [spec.dataset_id for spec in catalog]
    else:
        selected_ids = [str(item).strip().lower() for item in args.dataset_ids if str(item).strip()]

    if not selected_ids:
        print("No datasets selected. Use --list, --id <dataset_id>, or --all.")
        return 2

    missing = [dataset_id for dataset_id in selected_ids if dataset_id not in by_id]
    if missing:
        for dataset_id in missing:
            print(f"Unknown dataset id: {dataset_id}")
        return 2

    for dataset_id in selected_ids:
        spec = by_id[dataset_id]
        print(f"==> Preparing {spec.dataset_id} ({spec.name})")
        payload = prepare_dataset(spec)
        dataset_dir = dataset_dir_for_spec(spec)
        print(
            "ready | size={size} | graphs={graphs} | pairs={pairs} | dir={path}".format(
                size=format_bytes_human(int(payload.get("storage_size_bytes") or 0)),
                graphs=int(payload.get("graph_file_count") or 0),
                pairs=int(payload.get("pair_count") or 0),
                path=str(Path(dataset_dir).resolve()),
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
