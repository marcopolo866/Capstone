#!/usr/bin/env python3
"""Cross-platform launcher for local native solver builds."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], env: dict[str, str], cwd: Path) -> int:
    completed = subprocess.run(cmd, env=env, cwd=str(cwd))
    return int(completed.returncode)


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
        "--cmake-generator",
        default="",
        help="Optional CMake generator override.",
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
    generator = str(args.cmake_generator or env.get("CMAKE_GENERATOR", "")).strip()
    if generator:
        env["CMAKE_GENERATOR"] = generator

    passthrough = list(args.passthrough or [])
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    if backend == "ps1":
        cmd = [
            "powershell",
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

    cmd = ["bash", "scripts/build-local.sh"]
    cmd.extend(passthrough)
    return run(cmd, env, repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
