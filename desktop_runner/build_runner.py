#!/usr/bin/env python3
"""Cross-platform launcher for packaging the desktop benchmark runner."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def prefer_msys2_mingw(env: dict[str, str]) -> None:
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
    env.setdefault("MINGW_ROOT", str(msys_mingw_bin.parent))


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    prefer_msys2_mingw(env)

    if os.name == "nt":
        cmd = [
            "powershell",
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
