#!/usr/bin/env python3
"""Remove local build artifacts produced by build-local/build-runner flows."""

# - Deletion targets are derived from shared solver discovery so the cleaner
#   follows the same layout assumptions as the build and packaging scripts.
# - Be conservative when expanding removal rules; this script should only touch
#   generated artifacts that the repository can recreate locally.

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


def remove_path(path: Path) -> tuple[bool, str | None]:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
            return True, None
        if path.is_dir():
            errors: list[str] = []

            def onerror(_fn, failed_path, exc_info):
                exc = exc_info[1]
                errors.append(f"{failed_path}: {exc}")

            shutil.rmtree(path, ignore_errors=False, onerror=onerror)
            if path.exists():
                detail = errors[0] if errors else "directory still exists after cleanup attempt"
                return False, detail
            return True, None
    except FileNotFoundError:
        return False, None
    except PermissionError as exc:
        return False, str(exc)
    except OSError as exc:
        return False, str(exc)
    return False, None


def unpatch_glasgow_build_tweaks(repo_root: Path, apply: bool) -> list[Path]:
    """Revert build-time Glasgow source tweaks applied by build-local-core.py."""
    touched: list[Path] = []
    glasgow_root = repo_root / "baselines" / "glasgow-subgraph-solver"
    if not glasgow_root.is_dir():
        return touched

    sip_path = glasgow_root / "gss" / "sip_decomposer.cc"
    if sip_path.is_file():
        sip_text = sip_path.read_text(encoding="utf-8")
        sip_updated = sip_text
        sip_updated = sip_updated.replace(
            "n_choose_k<loooong>(unmapped_target_vertices, static_cast<unsigned long>(isolated_pattern_vertices.size()));",
            "n_choose_k<loooong>(unmapped_target_vertices, isolated_pattern_vertices.size());",
        )
        sip_updated = sip_updated.replace(
            "factorial<loooong>(static_cast<unsigned long>(isolated_pattern_vertices.size()));",
            "factorial<loooong>(isolated_pattern_vertices.size());",
        )
        if sip_updated != sip_text:
            if apply:
                sip_path.write_text(sip_updated, encoding="utf-8")
            touched.append(sip_path)

    cmake_path = glasgow_root / "CMakeLists.txt"
    if cmake_path.is_file():
        cmake_text = cmake_path.read_text(encoding="utf-8")
        cmake_updated = cmake_text
        old_march_block = (
            "include(CheckCXXCompilerFlag)\n"
            "unset(COMPILER_SUPPORTS_MARCH_NATIVE CACHE)\n"
            "CHECK_CXX_COMPILER_FLAG(-march=native COMPILER_SUPPORTS_MARCH_NATIVE)\n"
            "if (COMPILER_SUPPORTS_MARCH_NATIVE)\n"
            "    add_compile_options(-march=native)\n"
            "endif (COMPILER_SUPPORTS_MARCH_NATIVE)\n"
        )
        new_march_block = (
            "include(CheckCXXCompilerFlag)\n"
            "option(GCS_ENABLE_MARCH_NATIVE \"Enable -march=native optimizations\" ON)\n"
            "if (GCS_ENABLE_MARCH_NATIVE)\n"
            "    unset(COMPILER_SUPPORTS_MARCH_NATIVE CACHE)\n"
            "    CHECK_CXX_COMPILER_FLAG(-march=native COMPILER_SUPPORTS_MARCH_NATIVE)\n"
            "    if (COMPILER_SUPPORTS_MARCH_NATIVE)\n"
            "        add_compile_options(-march=native)\n"
            "    endif (COMPILER_SUPPORTS_MARCH_NATIVE)\n"
            "endif (GCS_ENABLE_MARCH_NATIVE)\n"
        )
        if new_march_block in cmake_updated:
            cmake_updated = cmake_updated.replace(new_march_block, old_march_block, 1)
        if cmake_updated != cmake_text:
            if apply:
                cmake_path.write_text(cmake_updated, encoding="utf-8")
            touched.append(cmake_path)

    return touched


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
            # Headless Data Collection batch outputs
            repo_root / "data_collection" / "runs",
            # Remove full dist/ to also clean benchmark_output_* folders written
            # next to packaged runner binaries.
            repo_root / "dist",
            repo_root / "build/capstone-benchmark-runner",
            # Common benchmark run artifacts.
            repo_root / "outputs/generated",
            repo_root / "outputs/result.json",
            repo_root / "outputs/run_metrics.json",
            repo_root / "outputs/binaries_manifest.json",
            repo_root / "outputs/binaries_download_error.txt",
            repo_root / "outputs/solver_variants.json",
        ]
    )

    removed = []
    failed: list[tuple[Path, str]] = []
    for path in paths:
        if args.dry_run:
            exists = path.is_file() or path.is_symlink() or path.is_dir()
            if exists:
                removed.append(path)
            continue
        ok, error_text = remove_path(path)
        if ok:
            removed.append(path)
        elif error_text:
            failed.append((path, error_text))

    touched = unpatch_glasgow_build_tweaks(repo_root, apply=not args.dry_run)
    removed.extend(touched)

    # Clean up empty parent directories we created artifacts in.
    if not args.dry_run:
        for parent in [repo_root / "build", repo_root / "outputs"]:
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

    if failed:
        print(f"Skipped {len(failed)} locked/unremovable path(s).")
        for path, error_text in failed:
            try:
                rel = path.relative_to(repo_root)
            except ValueError:
                rel = path
            print(f" ! {rel}: {error_text}")
        print("Close any running benchmark processes or terminals holding those files open, then run `make clean` again.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
