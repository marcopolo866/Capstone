#!/usr/bin/env python3
"""Cross-platform launcher for packaging the desktop benchmark runner."""

# - This wrapper is intentionally thin; platform-specific behavior belongs in
#   the underlying packaging scripts, not in duplicated branching here.
# - Keep toolchain selection deterministic so packaged binaries and copied
#   runtime DLLs come from the same compiler distribution.

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def prefer_msys2_mingw(env: dict[str, str]) -> None:
    # Packaging on Windows is sensitive to mixed MinGW installations. Force the
    # known-good MSYS2 toolchain to the front of PATH before launching helpers.
    if os.name != "nt":
        return

    msys_mingw_bin = Path(r"C:\msys64\mingw64\bin")
    msys_usr_bin = Path(r"C:\msys64\usr\bin")
    if not (msys_mingw_bin / "g++.exe").is_file():
        return

    current = env.get("PATH", "")
    parts = [p for p in current.split(os.pathsep) if p]
    msys_mingw_bin_s = str(msys_mingw_bin)
    msys_usr_bin_s = str(msys_usr_bin)
    filtered = [
        p for p in parts
        if p.lower() not in {msys_mingw_bin_s.lower(), msys_usr_bin_s.lower()}
    ]
    env["PATH"] = os.pathsep.join([msys_mingw_bin_s, msys_usr_bin_s, *filtered])
    # Packaging needs the runtime DLLs that match the active MSYS2 MinGW toolchain.
    # Overwrite any stale inherited root (for example C:\mingw64) so the staged
    # binaries and copied DLLs come from the same distribution.
    env["MINGW_ROOT"] = str(msys_mingw_bin.parent)


def resolve_powershell_executable(env: dict[str, str]) -> str:
    candidates = ["powershell", "pwsh"] if os.name == "nt" else ["pwsh", "powershell"]
    for name in candidates:
        found = shutil.which(name, path=env.get("PATH"))
        if found:
            return found
    return candidates[0]


def main() -> int:
    # Resolve the repo root once and delegate the real work to the platform
    # specific packaging entrypoints so local and CI packaging stay aligned.
    repo_root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    env["CAPSTONE_PYTHON_EXE"] = sys.executable
    prefer_msys2_mingw(env)

    if os.name == "nt":
        powershell_exe = resolve_powershell_executable(env)
        cmd = [
            powershell_exe,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "desktop_runner/build_windows_exe.ps1",
        ]
    else:
        cmd = [
            sys.executable,
            "desktop_runner/build_unix_bundle.py",
        ]

    completed = subprocess.run(cmd, env=env, cwd=str(repo_root))
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
