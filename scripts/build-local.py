#!/usr/bin/env python3
"""Cross-platform launcher for local native solver builds."""

# - This wrapper chooses an execution backend but defers real build logic to
#   scripts/build-local-core.py plus the shell/PowerShell adapters.
# - Keep backend selection deterministic so developers and CI hit the same
#   build graph regardless of the platform convenience wrapper they call.

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], env: dict[str, str], cwd: Path) -> int:
    completed = subprocess.run(cmd, env=env, cwd=str(cwd))
    return int(completed.returncode)


def resolve_powershell_executable(env: dict[str, str]) -> str:
    candidates: list[str] = []
    if os.name == "nt":
        candidates.extend(["powershell", "pwsh"])
    else:
        candidates.extend(["pwsh", "powershell"])
    for name in candidates:
        found = shutil.which(name, path=env.get("PATH"))
        if found:
            return found
    return candidates[0]


def resolve_bash_executable(env: dict[str, str]) -> str:
    if os.name != "nt":
        return "bash"

    # In Windows CI, "bash.exe" can resolve to the WSL shim in System32.
    # Prefer MSYS2/Git Bash explicitly so backend=sh runs the intended script.
    candidates: list[Path] = []

    gpp_path = shutil.which("g++", path=env.get("PATH"))
    if gpp_path:
        gpp = Path(gpp_path)
        # .../msys64/mingw64/bin/g++.exe -> .../msys64/usr/bin/bash.exe
        if len(gpp.parents) >= 3:
            candidates.append(gpp.parents[2] / "usr" / "bin" / "bash.exe")

    candidates.extend(
        [
            Path(r"C:\msys64\usr\bin\bash.exe"),
            Path(r"C:\Program Files\Git\bin\bash.exe"),
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    which_bash = shutil.which("bash", path=env.get("PATH"))
    if which_bash:
        return which_bash
    return "bash"


def prepend_path(env: dict[str, str], path_str: str) -> None:
    if not path_str:
        return
    current = env.get("PATH", "")
    parts = [p for p in current.split(os.pathsep) if p]
    if any(p.lower() == path_str.lower() for p in parts):
        return
    env["PATH"] = os.pathsep.join([path_str, *parts])


def prepare_windows_bash_env(env: dict[str, str], bash_exe: str) -> None:
    if os.name != "nt":
        return
    try:
        bash_path = Path(bash_exe).resolve()
    except Exception:
        return

    # If this is an MSYS2 bash path, ensure both /usr/bin and mingw64/bin are
    # at the front so coreutils + compiler toolchain commands are available.
    # Example: C:\msys64\usr\bin\bash.exe
    if bash_path.name.lower() == "bash.exe" and bash_path.parent.name.lower() == "bin":
        usr_dir = bash_path.parent
        if usr_dir.parent.name.lower() == "usr":
            msys_root = usr_dir.parent.parent
            mingw64_bin = msys_root / "mingw64" / "bin"
            if mingw64_bin.is_dir():
                prepend_path(env, str(mingw64_bin))
            if usr_dir.is_dir():
                prepend_path(env, str(usr_dir))


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Build local/native solver binaries.")
    parser.add_argument(
        "--backend",
        choices=("auto", "sh", "ps1"),
        default="auto",
        help="Backend script to use. Default: auto",
    )
    parser.add_argument(
        "--validation",
        choices=("fast", "full"),
        default="",
        help="Validation tier. 'fast' skips expensive correctness checks, 'full' runs all validation.",
    )
    parser.add_argument(
        "--cmake-generator",
        default="",
        help="Optional CMake generator override.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip expensive validation checks (VF3 smoke + Glasgow parity).",
    )
    parser.add_argument(
        "--sanitizer",
        choices=("none", "address", "undefined"),
        default="",
        help="Optional sanitizer build mode.",
    )
    parser.add_argument(
        "--suppress-diagnostics",
        action="store_true",
        help="Suppress compiler warning and note diagnostics in the shared build core.",
    )
    parser.add_argument(
        "passthrough",
        nargs=argparse.REMAINDER,
        help="Additional arguments passed to the backend script.",
    )
    args = parser.parse_args()

    backend = args.backend
    if backend == "auto":
        backend = "ps1" if os.name == "nt" else "sh"

    env = dict(os.environ)
    python_dir = str(Path(sys.executable).resolve().parent)
    env["CAPSTONE_PYTHON_EXE"] = sys.executable
    prepend_path(env, python_dir)

    generator = str(args.cmake_generator or env.get("CMAKE_GENERATOR", "")).strip()
    if generator:
        env["CMAKE_GENERATOR"] = generator

    if args.fast:
        env["BUILD_LOCAL_FAST"] = "1"
    if args.validation:
        env["BUILD_LOCAL_VALIDATION"] = args.validation
    if args.sanitizer:
        env["BUILD_LOCAL_SANITIZER"] = args.sanitizer
    if args.suppress_diagnostics:
        env["BUILD_LOCAL_SUPPRESS_DIAGNOSTICS"] = "1"

    passthrough = list(args.passthrough or [])
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    if backend == "ps1":
        powershell_exe = resolve_powershell_executable(env)
        cmd = [
            powershell_exe,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/build-local.ps1",
        ]
        if generator:
            cmd.extend(["-CMakeGenerator", generator])
        cmd.extend(passthrough)
        return run(cmd, env, repo_root)

    bash_exe = resolve_bash_executable(env)
    prepare_windows_bash_env(env, bash_exe)
    cmd = [bash_exe, "scripts/build-local.sh"]
    cmd.extend(passthrough)
    return run(cmd, env, repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
