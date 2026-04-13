from __future__ import annotations

# - Provenance collection should be best-effort and non-fatal; benchmarks still
#   need to complete if one host-introspection command is unavailable.
# - Keep field names stable because desktop, headless, and CI results all embed
#   this payload for later comparison.

import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import psutil  # type: ignore
except Exception:
    psutil = None


def _run_version_command(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception:
        return None
    text = str(completed.stdout or "").strip()
    if not text:
        return None
    first_line = text.splitlines()[0].strip()
    return first_line or None


def _git_output(repo_root: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception:
        return None
    text = str(completed.stdout or "").strip()
    return text or None


def _load_json_if_exists(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def collect_runtime_provenance(
    *,
    repo_root: Path | None = None,
    env: dict[str, str] | None = None,
    binaries_manifest_path: Path | None = None,
) -> dict:
    repo_root = (repo_root or Path.cwd()).resolve()
    env_map = {str(k): str(v) for k, v in (env or os.environ).items()}
    logical_cores = None
    physical_cores = None
    memory_total_bytes = None
    if psutil is not None:
        try:
            logical_cores = int(psutil.cpu_count(logical=True) or 0) or None
        except Exception:
            logical_cores = None
        try:
            physical_cores = int(psutil.cpu_count(logical=False) or 0) or None
        except Exception:
            physical_cores = None
        try:
            memory_total_bytes = int(psutil.virtual_memory().total or 0) or None
        except Exception:
            memory_total_bytes = None
    if logical_cores is None:
        logical_cores = int(os.cpu_count() or 0) or None

    def tool_info(name: str, version_args: list[str] | None = None) -> dict | None:
        path = shutil.which(name, path=env_map.get("PATH"))
        if not path:
            return None
        return {
            "path": path,
            "version": _run_version_command([path, *(version_args or ["--version"])]),
        }

    build_flags = {
        "CMAKE_GENERATOR": env_map.get("CMAKE_GENERATOR") or None,
        "CFLAGS": env_map.get("CFLAGS") or None,
        "CXXFLAGS": env_map.get("CXXFLAGS") or None,
        "CPPFLAGS": env_map.get("CPPFLAGS") or None,
        "LDFLAGS": env_map.get("LDFLAGS") or None,
    }
    build_flags = {key: value for key, value in build_flags.items() if value not in {None, ""}}

    git_sha = env_map.get("GITHUB_SHA") or _git_output(repo_root, ["rev-parse", "HEAD"])
    git_ref = (
        env_map.get("GITHUB_REF_NAME")
        or env_map.get("GITHUB_REF")
        or _git_output(repo_root, ["branch", "--show-current"])
    )

    binaries_manifest = _load_json_if_exists(binaries_manifest_path or (repo_root / "outputs" / "binaries_manifest.json"))
    build_artifact_provenance = None
    if isinstance(binaries_manifest, dict):
        artifact = binaries_manifest.get("build_provenance")
        if isinstance(artifact, dict):
            build_artifact_provenance = artifact

    return {
        "captured_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runtime_environment": {
            "python": {
                "version": sys.version.splitlines()[0].strip(),
                "executable": sys.executable,
                "implementation": platform.python_implementation(),
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "platform": platform.platform(),
            },
            "hardware": {
                "logical_cores": logical_cores,
                "physical_cores": physical_cores,
                "memory_total_bytes": memory_total_bytes,
            },
            "git": {
                "sha": git_sha,
                "ref": git_ref,
            },
        },
        "toolchains": {
            key: value
            for key, value in {
                "cmake": tool_info("cmake"),
                "g++": tool_info("g++"),
                "gcc": tool_info("gcc"),
                "clang++": tool_info("clang++"),
                "clang": tool_info("clang"),
                "make": tool_info("make"),
                "python": {
                    "path": sys.executable,
                    "version": sys.version.splitlines()[0].strip(),
                },
            }.items()
            if value is not None
        },
        "build_flags": build_flags,
        "artifact_build_provenance": build_artifact_provenance,
    }
