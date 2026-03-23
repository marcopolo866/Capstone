#!/usr/bin/env python3
"""Remove local build artifacts produced by build-local/build-runner flows."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


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
    paths = [
        # Native solver outputs
        repo_root / "baselines/dijkstra",
        repo_root / "baselines/dijkstra.exe",
        repo_root / "src/dijkstra_llm",
        repo_root / "src/dijkstra_llm.exe",
        repo_root / "src/dijkstra_gemini",
        repo_root / "src/dijkstra_gemini.exe",
        repo_root / "src/vf3",
        repo_root / "src/vf3.exe",
        repo_root / "src/chatvf3",
        repo_root / "src/chatvf3.exe",
        repo_root / "src/glasgow_chatgpt",
        repo_root / "src/glasgow_chatgpt.exe",
        repo_root / "src/glasgow_gemini",
        repo_root / "src/glasgow_gemini.exe",
        repo_root / "baselines/vf3lib/bin/vf3",
        repo_root / "baselines/vf3lib/bin/vf3.exe",
        repo_root / "baselines/glasgow-subgraph-solver/build",
        # Desktop runner packaging outputs
        repo_root / "desktop_runner/.staging",
        # Remove full dist/ to also clean benchmark_output_* folders written
        # next to packaged runner binaries.
        repo_root / "dist",
        repo_root / "build/capstone-benchmark-runner",
    ]

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
