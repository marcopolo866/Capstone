#!/usr/bin/env python3
"""Remove local build artifacts produced by build-local/build-runner flows."""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path


def load_solver_discovery(repo_root: Path):
    module_path = repo_root / "scripts" / "solver_discovery.py"
    spec = importlib.util.spec_from_file_location("solver_discovery", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load solver discovery module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def remove_path(path: Path) -> bool:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return True
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove local build artifacts.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show paths that would be removed without deleting them.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    solver_discovery = load_solver_discovery(repo_root)
    catalog = solver_discovery.build_catalog(repo_root)

    paths = []
    binary_rel_paths = set()
    for rel in solver_discovery.iter_binary_paths(catalog, include_baselines=True):
        binary_rel_paths.add(rel)

    # Legacy binary names kept for cleanup compatibility with older builds.
    binary_rel_paths.update(
        {
            "src/dijkstra_llm",
            "src/chatvf3",
            "src/vf3",
        }
    )

    for rel in sorted(binary_rel_paths):
        base = repo_root / rel
        paths.append(base)
        paths.append(base.with_suffix(base.suffix + ".exe"))

    paths.extend(
        [
            # Glasgow CMake build directory
            repo_root / "baselines/glasgow-subgraph-solver/build",
            # Desktop runner packaging outputs
            repo_root / "desktop_runner/.staging",
            # Remove full dist/ to also clean benchmark_output_* folders written
            # next to packaged runner binaries.
            repo_root / "dist",
            repo_root / "build/capstone-benchmark-runner",
            repo_root / "outputs/solver_variants.json",
        ]
    )

    removed = []
    for path in paths:
        if args.dry_run:
            exists = path.is_file() or path.is_symlink() or path.is_dir()
            if exists:
                removed.append(path)
            continue
        if remove_path(path):
            removed.append(path)

    # Clean up empty parent directories we created artifacts in.
    if not args.dry_run:
        for parent in [repo_root / "build"]:
            try:
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass

    action = "Would remove" if args.dry_run else "Removed"
    print(f"{action} {len(removed)} local build artifact path(s).")
    for path in removed:
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            rel = path
        print(f" - {rel}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
