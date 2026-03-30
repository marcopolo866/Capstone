#!/usr/bin/env python3
"""Single-source implementation of local native solver builds."""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def env_truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def prepend_path(env: dict[str, str], value: str) -> None:
    if not value:
        return
    current = env.get("PATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    if os.name == "nt":
        if any(part.lower() == value.lower() for part in parts):
            return
    else:
        if value in parts:
            return
    env["PATH"] = os.pathsep.join([value, *parts])


def run_cmd(cmd: list[str], env: dict[str, str], cwd: Path | None = None) -> None:
    completed = subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), env=env)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(cmd)}")


def run_step(label: str, fn) -> None:
    print()
    print(f"==> {label}")
    fn()


def ensure_command(name: str, env: dict[str, str]) -> str:
    found = shutil.which(name, path=env.get("PATH"))
    if not found:
        raise RuntimeError(f"Missing required command: {name}")
    return found


def prefer_msys2_toolchain(env: dict[str, str]) -> None:
    if os.name != "nt":
        return
    msys_mingw_bin = Path(r"C:\msys64\mingw64\bin")
    msys_usr_bin = Path(r"C:\msys64\usr\bin")
    if not (msys_mingw_bin / "g++.exe").is_file():
        return
    current_gpp = shutil.which("g++", path=env.get("PATH")) or ""
    if current_gpp:
        try:
            resolved = str(Path(current_gpp).resolve())
        except OSError:
            resolved = current_gpp
        if resolved.lower().startswith(str(msys_mingw_bin).lower()):
            return
    print(f"Preferring MSYS2 MinGW toolchain from {msys_mingw_bin}")
    prepend_path(env, str(msys_usr_bin))
    prepend_path(env, str(msys_mingw_bin))


def assert_gmp_available_windows(env: dict[str, str]) -> None:
    if os.name != "nt":
        return
    gpp = ensure_command("g++", env)
    bin_dir = Path(gpp).resolve().parent
    tool_root = bin_dir.parent
    lib_dir = tool_root / "lib"
    has_gmp = (lib_dir / "libgmp.dll.a").is_file() or (lib_dir / "libgmp.a").is_file()
    has_gmpxx = (lib_dir / "libgmpxx.dll.a").is_file() or (lib_dir / "libgmpxx.a").is_file()
    if has_gmp and has_gmpxx:
        return
    raise RuntimeError(
        "Missing GMP/GMPXX development libraries for the active compiler:\n"
        f"  g++: {gpp}\n"
        f"  expected under: {lib_dir}\n\n"
        "If using MSYS2, install with:\n"
        '  C:\\msys64\\usr\\bin\\bash.exe -lc "pacman -S --needed '
        'mingw-w64-x86_64-gcc mingw-w64-x86_64-cmake mingw-w64-x86_64-make '
        'mingw-w64-x86_64-gmp"'
    )


def load_solver_discovery_module():
    module_path = REPO_ROOT / "scripts" / "solver_discovery.py"
    spec = importlib.util.spec_from_file_location("solver_discovery", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load solver discovery module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def resolve_binary_path(base_rel: str) -> Path | None:
    raw = REPO_ROOT / base_rel
    if raw.is_file():
        return raw.resolve()
    exe = raw.with_suffix(raw.suffix + ".exe")
    if exe.is_file():
        return exe.resolve()
    return None


def output_exists(base_rel: str) -> bool:
    return resolve_binary_path(base_rel) is not None


def is_msys_or_cygwin_shell() -> bool:
    ostype = str(os.environ.get("OSTYPE", "")).lower()
    return ostype.startswith("msys") or ostype.startswith("cygwin") or ostype.startswith("win32")


def reset_glasgow_build_dir_if_needed(build_dir: Path, expected_generator: str) -> None:
    cache_path = build_dir / "CMakeCache.txt"
    if not cache_path.is_file():
        return
    try:
        cache_text = cache_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    cached_generator = ""
    for line in cache_text.splitlines():
        if line.startswith("CMAKE_GENERATOR:INTERNAL="):
            cached_generator = line.split("=", 1)[1].strip()
            break

    if expected_generator and cached_generator and cached_generator != expected_generator:
        print(
            f"Cleaning stale Glasgow CMake build directory (generator mismatch: "
            f"'{cached_generator}' vs '{expected_generator}')"
        )
        shutil.rmtree(build_dir, ignore_errors=True)
        return

    cwd_text = str(Path.cwd()).replace("\\", "/").lower()
    path_style_mismatch = (
        bool(os.name == "nt" or is_msys_or_cygwin_shell() or cwd_text.startswith("/mnt/") or cwd_text.startswith("/c/"))
        and re.search(r"(?mi)^CMAKE_HOME_DIRECTORY:INTERNAL=[A-Za-z]:/", cache_text) is not None
    )
    if path_style_mismatch:
        print("Cleaning stale Glasgow CMake build directory (Windows/Git Bash CMake cache path style mismatch)")
        shutil.rmtree(build_dir, ignore_errors=True)


def _read_cmake_cache_value(cache_text: str, key: str) -> str:
    prefix = f"{key}:"
    for line in cache_text.splitlines():
        if not line.startswith(prefix):
            continue
        _, _, value = line.partition("=")
        return value.strip()
    return ""


def reset_glasgow_build_dir_for_compiler_mismatch(build_dir: Path, env: dict[str, str]) -> None:
    cache_path = build_dir / "CMakeCache.txt"
    if not cache_path.is_file():
        return
    try:
        cache_text = cache_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    cached_compiler = _read_cmake_cache_value(cache_text, "CMAKE_CXX_COMPILER")
    if not cached_compiler:
        return
    current_compiler = shutil.which("g++", path=env.get("PATH")) or ""
    if not current_compiler:
        return

    try:
        cached_resolved = str(Path(cached_compiler).resolve())
    except OSError:
        cached_resolved = cached_compiler
    try:
        current_resolved = str(Path(current_compiler).resolve())
    except OSError:
        current_resolved = current_compiler

    if cached_resolved.lower() == current_resolved.lower():
        return

    print(
        "Cleaning stale Glasgow CMake build directory (compiler mismatch: "
        f"'{cached_resolved}' vs '{current_resolved}')"
    )
    shutil.rmtree(build_dir, ignore_errors=True)


def ensure_glasgow_compiler_runtime_on_path(build_dir: Path, env: dict[str, str]) -> None:
    cache_path = build_dir / "CMakeCache.txt"
    if not cache_path.is_file():
        return
    try:
        cache_text = cache_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    cached_compiler = _read_cmake_cache_value(cache_text, "CMAKE_CXX_COMPILER")
    if not cached_compiler:
        return
    try:
        compiler_bin = Path(cached_compiler).resolve().parent
    except OSError:
        return
    if compiler_bin.is_dir():
        prepend_path(env, str(compiler_bin))

    # If using MSYS2 MinGW, cc1plus lives under lib/gcc and needs mingw/bin on PATH.
    compiler_path_lower = str(compiler_bin).lower().replace("\\", "/")
    if "/msys64/mingw64/bin" in compiler_path_lower:
        msys_usr = compiler_bin.parent.parent / "usr" / "bin"
        if msys_usr.is_dir():
            prepend_path(env, str(msys_usr))


def compile_discovered_variants_for_family(catalog: dict, family: str, env: dict[str, str]) -> None:
    rows = [
        row
        for row in (catalog.get("variants") or [])
        if str(row.get("family", "")).strip().lower() == family
    ]
    rows.sort(key=lambda row: (str(row.get("llm_label", "")).lower(), str(row.get("variant_id", "")).lower()))
    if not rows:
        print()
        print(f"==> No discovered {family} variants in src/")
        return

    for row in rows:
        label = str(row.get("label") or row.get("variant_id") or "variant")
        source = str(row.get("source_path") or "").strip()
        binary = str(row.get("binary_path") or "").strip()
        if not source or not binary:
            continue

        def _build() -> None:
            suppress_diagnostics = env_truthy(env.get("BUILD_LOCAL_SUPPRESS_DIAGNOSTICS", ""))
            compile_flags = [
                "g++",
                "-std=c++17",
                "-O3",
            ]
            if suppress_diagnostics:
                compile_flags.append("-w")
            else:
                compile_flags.extend(["-Wall", "-Wextra"])
            run_cmd(
                [*compile_flags, source, "-o", binary],
                env=env,
            )

        run_step(f"Building {label}", _build)


def run_vf3_smoke_test(python_exe: str, env: dict[str, str]) -> None:
    vf3_binary = resolve_binary_path("baselines/vf3lib/bin/vf3")
    if vf3_binary is None:
        raise RuntimeError("Missing VF3 baseline binary for smoke test")

    with tempfile.TemporaryDirectory(prefix="vf3_smoke_") as tmp_dir:
        generated = subprocess.run(
            [
                python_exe,
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
                tmp_dir,
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        lines = [line.strip() for line in generated.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("Generator produced no output for VF3 smoke test.")
        parts = [part.strip() for part in lines[-1].split(",")]
        if len(parts) < 4:
            raise RuntimeError(f"Failed to parse generated VF paths from output: {lines[-1]}")
        vf_pattern = Path(parts[2]).resolve()
        vf_target = Path(parts[3]).resolve()
        if not vf_pattern.is_file():
            raise RuntimeError(f"Generated VF pattern missing: {vf_pattern}")
        if not vf_target.is_file():
            raise RuntimeError(f"Generated VF target missing: {vf_target}")

        completed = subprocess.run(
            [str(vf3_binary), "-u", "-r", "0", "-e", str(vf_pattern), str(vf_target)],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"VF3 baseline smoke test failed with code {completed.returncode}.")


def patch_glasgow_submodule() -> None:
    patched_any = False

    sip_path = REPO_ROOT / "baselines/glasgow-subgraph-solver/gss/sip_decomposer.cc"
    sip_text = sip_path.read_text(encoding="utf-8")
    sip_updated = sip_text
    sip_updated = sip_updated.replace(
        "n_choose_k<loooong>(unmapped_target_vertices, isolated_pattern_vertices.size());",
        "n_choose_k<loooong>(unmapped_target_vertices, static_cast<unsigned long>(isolated_pattern_vertices.size()));",
    )
    sip_updated = sip_updated.replace(
        "factorial<loooong>(isolated_pattern_vertices.size());",
        "factorial<loooong>(static_cast<unsigned long>(isolated_pattern_vertices.size()));",
    )
    if sip_updated != sip_text:
        sip_path.write_text(sip_updated, encoding="utf-8")
        print(f"Patched {sip_path}")
        patched_any = True
    else:
        print(f"No patch changes needed for {sip_path}")

    cmake_path = REPO_ROOT / "baselines/glasgow-subgraph-solver/CMakeLists.txt"
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
    if old_march_block in cmake_updated:
        cmake_updated = cmake_updated.replace(old_march_block, new_march_block, 1)
    if cmake_updated != cmake_text:
        cmake_path.write_text(cmake_updated, encoding="utf-8")
        print(f"Patched {cmake_path}")
        patched_any = True
    else:
        print(f"No patch changes needed for {cmake_path}")

    if not patched_any:
        print("No Glasgow submodule patch changes were required.")


def maybe_run_glasgow_parity_check(python_exe: str, env: dict[str, str]) -> None:
    chat = resolve_binary_path("src/glasgow_chatgpt")
    gem = resolve_binary_path("src/glasgow_gemini")
    if not chat or not gem:
        print()
        print("==> Skipping Glasgow parity check (missing src/glasgow_chatgpt or src/glasgow_gemini)")
        return
    run_step("Checking Glasgow parity", lambda: run_cmd([python_exe, "scripts/check-glasgow-parity.py"], env=env))


def verify_expected_outputs(catalog: dict, solver_discovery) -> None:
    binary_rel_paths = set(solver_discovery.iter_binary_paths(catalog, include_baselines=True))
    missing = [rel for rel in sorted(binary_rel_paths) if not output_exists(rel)]
    if missing:
        joined = "\n".join(missing)
        raise RuntimeError(f"Build completed with missing outputs:\n{joined}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local/native solver binaries.")
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
        "passthrough",
        nargs=argparse.REMAINDER,
        help="Extra args accepted for compatibility (ignored).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = dict(os.environ)
    prefer_msys2_toolchain(env)

    ensure_command("git", env)
    ensure_command("g++", env)
    ensure_command("make", env)
    ensure_command("cmake", env)
    assert_gmp_available_windows(env)

    python_exe = sys.executable
    fast_mode = bool(args.fast or env_truthy(env.get("BUILD_LOCAL_FAST", "")))
    portable_mode = bool(
        env_truthy(env.get("BUILD_LOCAL_PORTABLE", ""))
        or (
            env_truthy(env.get("GITHUB_ACTIONS", ""))
            and not env_truthy(env.get("BUILD_LOCAL_ALLOW_NATIVE", ""))
        )
    )
    if fast_mode:
        print("BUILD_LOCAL_FAST enabled: skipping VF3 smoke + Glasgow parity checks")
    if portable_mode:
        print("BUILD_LOCAL_PORTABLE enabled: disabling Glasgow -march=native for portable binaries")
    suppress_diagnostics = env_truthy(env.get("BUILD_LOCAL_SUPPRESS_DIAGNOSTICS", ""))
    if suppress_diagnostics:
        print("BUILD_LOCAL_SUPPRESS_DIAGNOSTICS enabled: suppressing warning/note diagnostics")

    if env_truthy(env.get("BUILD_LOCAL_SKIP_SUBMODULE_UPDATE", "")):
        print()
        print("==> Skipping submodule update (BUILD_LOCAL_SKIP_SUBMODULE_UPDATE=1)")
    else:
        run_step("Updating submodules", lambda: run_cmd(["git", "submodule", "update", "--init", "--recursive"], env=env))

    solver_discovery = load_solver_discovery_module()
    catalog = solver_discovery.build_catalog(REPO_ROOT)

    run_step(
        "Building Dijkstra baseline",
        lambda: run_cmd(
            [
                "g++",
                "-std=c++17",
                "-O3",
                *([] if not suppress_diagnostics else ["-w"]),
                *([] if suppress_diagnostics else ["-Wall", "-Wextra"]),
                "-I",
                "baselines/nyaan-library",
                "baselines/dijkstra_main.cpp",
                "-o",
                "baselines/dijkstra",
            ],
            env=env,
        ),
    )
    compile_discovered_variants_for_family(catalog, "dijkstra", env)

    vf3_cflags = "-std=c++11 -O2 -DNDEBUG -Wno-deprecated -fno-strict-aliasing -fwrapv"
    if suppress_diagnostics:
        vf3_cflags += " -w"
    if os.name == "nt":
        vf3_cflags += " -DWIN32 -include getopt.h"

    def clean_vf3_outputs() -> None:
        for rel in ("baselines/vf3lib/bin/vf3", "baselines/vf3lib/bin/vf3.exe"):
            path = REPO_ROOT / rel
            if path.is_file():
                path.unlink()

    run_step("Cleaning VF3 baseline outputs (fresh rebuild)", clean_vf3_outputs)
    run_step("Building VF3 baseline (vf3lib)", lambda: run_cmd(["make", "-C", "baselines/vf3lib", "vf3", f"CFLAGS={vf3_cflags}"], env=env))

    if fast_mode:
        print()
        print("==> Skipping VF3 baseline smoke test (BUILD_LOCAL_FAST=1)")
    else:
        run_step("VF3 baseline smoke test (small generated subgraph case)", lambda: run_vf3_smoke_test(python_exe, env))

    compile_discovered_variants_for_family(catalog, "vf3", env)
    compile_discovered_variants_for_family(catalog, "glasgow", env)

    run_step("Patching Glasgow submodule for MinGW loooong/size_t ambiguity", patch_glasgow_submodule)

    generator = str(args.cmake_generator or env.get("CMAKE_GENERATOR", "")).strip()
    if not generator and is_msys_or_cygwin_shell():
        generator = "MinGW Makefiles"

    cmake_cxx_flags = "-O3 -w" if suppress_diagnostics else "-O3"
    cmake_c_flags = "-O3 -w" if suppress_diagnostics else "-O3"
    cmake_args = [
        "cmake",
        *(["-Wno-dev"] if suppress_diagnostics else []),
        "-S",
        "baselines/glasgow-subgraph-solver",
        "-B",
        "baselines/glasgow-subgraph-solver/build",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_CXX_FLAGS={cmake_cxx_flags}",
        f"-DCMAKE_C_FLAGS={cmake_c_flags}",
        *([] if not suppress_diagnostics else ["-DCMAKE_SUPPRESS_DEVELOPER_WARNINGS=ON"]),
        f"-DGCS_ENABLE_MARCH_NATIVE={'OFF' if portable_mode else 'ON'}",
    ]
    if generator:
        cmake_args.extend(["-G", generator])

    build_dir = REPO_ROOT / "baselines/glasgow-subgraph-solver/build"
    reset_glasgow_build_dir_if_needed(build_dir, generator)
    reset_glasgow_build_dir_for_compiler_mismatch(build_dir, env)

    run_step("Configuring Glasgow baseline", lambda: run_cmd(cmake_args, env=env))
    ensure_glasgow_compiler_runtime_on_path(build_dir, env)
    run_step(
        "Building Glasgow baseline",
        lambda: run_cmd(
            [
                "cmake",
                "--build",
                "baselines/glasgow-subgraph-solver/build",
                "--config",
                "Release",
                "--parallel",
            ],
            env=env,
        ),
    )

    if fast_mode:
        print()
        print("==> Skipping Glasgow parity check (BUILD_LOCAL_FAST=1)")
    else:
        maybe_run_glasgow_parity_check(python_exe, env)

    verify_expected_outputs(catalog, solver_discovery)

    print()
    print("Local build complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
