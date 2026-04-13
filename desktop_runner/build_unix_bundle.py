#!/usr/bin/env python3
"""Package the desktop benchmark runner on Linux/macOS."""

# - This script owns the Unix staging layout for the desktop bundle; keep the
#   staged binaries, copied assets, and final archive contents in sync.
# - Solver discovery and build invocation intentionally come from the shared
#   scripts/ helpers so packaging does not drift from normal local builds.

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
# Staging is rebuilt from scratch for each run so the archive only contains the
# exact binaries and assets produced by the current packaging invocation.
STAGING_ROOT = REPO_ROOT / "desktop_runner" / ".staging"
STAGING_BIN = STAGING_ROOT / "binaries"
DIST_DIR = REPO_ROOT / "dist"


def load_solver_discovery():
    module_path = REPO_ROOT / "scripts" / "solver_discovery.py"
    spec = importlib.util.spec_from_file_location("solver_discovery", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load solver discovery module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_step(label: str, cmd: list[str], cwd: Path | None = None) -> None:
    print()
    print(f"==> {label}")
    subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=True)


def resolve_binary(candidates: list[str]) -> Path:
    for rel in candidates:
        path = REPO_ROOT / rel
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(f"Missing required binary. Tried: {', '.join(candidates)}")


def ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def parse_generated_vf_paths(generator_stdout: str) -> tuple[Path, Path]:
    lines = [line.strip() for line in generator_stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Generator produced no output for VF3 smoke test.")
    last = lines[-1]
    parts = [p.strip() for p in last.split(",")]
    if len(parts) < 4:
        raise RuntimeError(f"Failed to parse generated VF paths from output: {last}")
    vf_pattern = Path(parts[2]).resolve()
    vf_target = Path(parts[3]).resolve()
    if not vf_pattern.is_file():
        raise RuntimeError(f"Generated VF pattern missing for smoke test: {vf_pattern}")
    if not vf_target.is_file():
        raise RuntimeError(f"Generated VF target missing for smoke test: {vf_target}")
    return vf_pattern, vf_target


def run_staged_vf3_smoke_test(vf3_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="vf3_pkg_smoke_") as tmp:
        generator_cmd = [
            sys.executable,
            "utilities/generate_graphs.py",
            "--algorithm",
            "subgraph",
            "--n",
            "5",
            "--k",
            "2",
            "--density",
            "0.01",
            "--seed",
            "424242",
            "--out-dir",
            tmp,
        ]
        print()
        print("==> VF3 staged smoke test")
        gen = subprocess.run(
            generator_cmd,
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        vf_pattern, vf_target = parse_generated_vf_paths(gen.stdout)
        probe = subprocess.run(
            [str(vf3_path), "-u", "-r", "0", "-e", str(vf_pattern), str(vf_target)],
            cwd=str(vf3_path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if probe.returncode != 0:
            detail = (probe.stderr or probe.stdout or "").strip()
            raise RuntimeError(
                f"Staged VF3 smoke test failed for {vf3_path} with code {probe.returncode}. {detail[:4000]}"
            )
        print(f"VF3 smoke test passed: {vf3_path}")


def stage_binaries() -> list[Path]:
    solver_discovery = load_solver_discovery()
    catalog = solver_discovery.build_catalog(REPO_ROOT)
    binary_spec: list[tuple[str, list[str], dict]] = []
    for row in catalog.get("solvers", []):
        if not isinstance(row, dict):
            continue
        variant_id = str(row.get("variant_id") or "").strip()
        binary_path = str(row.get("binary_path") or "").strip()
        if not variant_id or not binary_path:
            continue
        candidates = [binary_path]
        if variant_id == "glasgow_baseline":
            candidates.extend(
                [
                    "baselines/glasgow-subgraph-solver/build/Release/glasgow_subgraph_solver",
                    "baselines/glasgow-subgraph-solver/build/src/glasgow_subgraph_solver",
                    "baselines/glasgow-subgraph-solver/build/src/Release/glasgow_subgraph_solver",
                ]
            )
        elif variant_id == "dijkstra_chatgpt":
            candidates.append("src/dijkstra_llm")
        elif variant_id == "vf3_chatgpt":
            candidates.append("src/chatvf3")
        elif variant_id == "vf3_gemini":
            candidates.append("src/vf3")
        binary_spec.append((variant_id, candidates, row))

    if STAGING_ROOT.exists():
        shutil.rmtree(STAGING_ROOT)
    STAGING_BIN.mkdir(parents=True, exist_ok=True)

    staged: list[Path] = []
    staged_rows: list[dict] = []
    for out_name, candidates, row in binary_spec:
        resolved = resolve_binary(candidates)
        target = STAGING_BIN / out_name
        shutil.copy2(resolved, target)
        ensure_executable(target)
        staged.append(target)
        print(f"Using binary {out_name}: {resolved}")
        staged_rows.append(
            {
                "variant_id": out_name,
                "family": str(row.get("family") or ""),
                "algorithm": str(row.get("algorithm") or ""),
                "role": str(row.get("role") or ""),
                "label": str(row.get("label") or out_name),
                "llm_key": row.get("llm_key"),
                "llm_label": row.get("llm_label"),
                "binary_name": out_name,
            }
        )

    manifest_path = STAGING_BIN / "solver_variants.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "solvers": staged_rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    staged.append(manifest_path)

    run_staged_vf3_smoke_test(STAGING_BIN / "vf3_baseline")
    return staged


def package_runner(staged_files: list[Path]) -> list[Path]:
    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "capstone-benchmark-runner",
        "--hidden-import",
        "matplotlib.backends.backend_tkagg",
        "--hidden-import",
        "matplotlib.backends.backend_agg",
        "--collect-submodules",
        "webview",
        "desktop_runner/app.py",
    ]
    for file_path in staged_files:
        pyinstaller_cmd.extend(["--add-binary", f"{file_path}{os.pathsep}binaries"])

    visualizer_js = REPO_ROOT / "js" / "app" / "07-visualization-api-bootstrap.js"
    if not visualizer_js.is_file():
        raise RuntimeError(f"Missing visualizer bootstrap script: {visualizer_js}")
    pyinstaller_cmd.extend(["--add-data", f"{visualizer_js}{os.pathsep}js/app"])

    run_step("PyInstaller desktop runner bundle", pyinstaller_cmd, cwd=REPO_ROOT)

    candidates = [
        DIST_DIR / "capstone-benchmark-runner",
        DIST_DIR / "capstone-benchmark-runner.app",
    ]
    produced = [path for path in candidates if path.exists()]
    if not produced:
        raise RuntimeError(
            "No packaged desktop runner found in dist/. "
            "Expected capstone-benchmark-runner or capstone-benchmark-runner.app"
        )
    for path in produced:
        print(f"Built: {path}")
    return produced


def main() -> int:
    if os.name == "nt":
        raise SystemExit("build_unix_bundle.py is for Linux/macOS only. Use build_windows_exe.ps1 on Windows.")

    staged = stage_binaries()
    package_runner(staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
