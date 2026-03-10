#!/usr/bin/env bash
# Build local benchmark binaries used by the UI and GitHub artifact workflow.
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage: bash scripts/build-local.sh

Builds the local/native binaries used by the benchmark workflows:
- Dijkstra baseline + LLM variants
- VF3 baseline + LLM variants
- Glasgow solver + LLM variants

Environment:
- CMAKE_GENERATOR: optional CMake generator override
  Example (Windows Git Bash/MSYS2): CMAKE_GENERATOR="MinGW Makefiles"
EOF
  exit 0
fi

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

run_step() {
  local label="$1"
  shift
  echo
  echo "==> $label"
  "$@"
}

output_exists() {
  local path="$1"
  [[ -f "$path" ]] && return 0
  [[ -f "${path}.exe" ]] && return 0
  return 1
}

reset_glasgow_build_dir_if_needed() {
  local build_dir="baselines/glasgow-subgraph-solver/build"
  local cache_path="${build_dir}/CMakeCache.txt"
  local expected_generator="${1:-}"
  [[ -f "$cache_path" ]] || return 0

  local cached_generator=""
  cached_generator="$(sed -n 's/^CMAKE_GENERATOR:INTERNAL=//p' "$cache_path" | head -n1 || true)"

  local pwd_unix=""
  pwd_unix="$(pwd 2>/dev/null || true)"
  local pwd_native=""
  pwd_native="$(pwd -W 2>/dev/null || true)"

  local cache_mismatch=0
  if [[ -n "$expected_generator" && -n "$cached_generator" && "$cached_generator" != "$expected_generator" ]]; then
    cache_mismatch=1
    echo "Cleaning stale Glasgow CMake build directory (generator mismatch: '$cached_generator' vs '$expected_generator')"
  elif { [[ -n "$pwd_native" ]] || [[ "$pwd_unix" == /mnt/* ]] || [[ "$pwd_unix" == /c/* ]]; } \
    && grep -qi '^CMAKE_HOME_DIRECTORY:INTERNAL=[A-Za-z]:/' "$cache_path" 2>/dev/null; then
    # Git Bash/MSYS path style mismatch against a prior Windows-native CMake configure.
    cache_mismatch=1
    echo "Cleaning stale Glasgow CMake build directory (Windows/Git Bash CMake cache path style mismatch)"
  fi

  if [[ "$cache_mismatch" -eq 1 ]]; then
    rm -rf "$build_dir"
  fi
}

need_cmd git
need_cmd g++
need_cmd make
need_cmd cmake
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Missing required command: python3 (or python)" >&2
  exit 1
fi

run_step "Updating submodules" git submodule update --init --recursive

run_step "Building Dijkstra baseline" \
  g++ -std=c++17 -O3 -Wall -Wextra -I "baselines/nyaan-library" "baselines/dijkstra_main.cpp" -o "baselines/dijkstra"
run_step "Building Dijkstra ChatGPT" \
  g++ -std=c++17 -O3 -Wall -Wextra "src/[CHATGPT] Shortest Path.cpp" -o "src/dijkstra_llm"
run_step "Building Dijkstra Gemini" \
  g++ -std=c++17 -O3 -Wall -Wextra "src/[GEMINI] Shortest Path.cpp" -o "src/dijkstra_gemini"

vf3_cflags="-std=c++11 -O3 -DNDEBUG -Wno-deprecated"
if [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* || "${OSTYPE:-}" == win32* ]]; then
  # vf3lib uses WIN32 guards in main.cpp, while MinGW typically defines _WIN32.
  vf3_cflags="${vf3_cflags} -DWIN32"
fi
run_step "Building VF3 baseline (vf3lib)" \
  make -C baselines/vf3lib vf3 CFLAGS="${vf3_cflags}"
run_step "Building VF3 Gemini" \
  g++ -std=c++17 -O3 -Wall -Wextra "src/[GEMINI] Subgraph Isomorphism.cpp" -o "src/vf3"
run_step "Building VF3 ChatGPT" \
  g++ -std=c++17 -O3 -Wall -Wextra "src/[CHATGPT] Subgraph Isomorphism.cpp" -o "src/chatvf3"

run_step "Building Glasgow ChatGPT" \
  g++ -std=c++17 -O3 -Wall -Wextra "src/[CHATGPT] Glasgow.cpp" -o "src/glasgow_chatgpt"
run_step "Building Glasgow Gemini" \
  g++ -std=c++17 -O3 -Wall -Wextra "src/[GEMINI] Glasgow.cpp" -o "src/glasgow_gemini"

cmake_args=(
  -S "baselines/glasgow-subgraph-solver"
  -B "baselines/glasgow-subgraph-solver/build"
  -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_CXX_FLAGS=-O3
)

if [[ -n "${CMAKE_GENERATOR:-}" ]]; then
  cmake_args+=(-G "${CMAKE_GENERATOR}")
elif [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* ]]; then
  # Match the prior documented Windows Git Bash/MSYS2 path.
  cmake_args+=(-G "MinGW Makefiles")
fi

expected_generator=""
for ((i=0; i<${#cmake_args[@]}; i++)); do
  if [[ "${cmake_args[$i]}" == "-G" && $((i+1)) -lt ${#cmake_args[@]} ]]; then
    expected_generator="${cmake_args[$((i+1))]}"
    break
  fi
done
reset_glasgow_build_dir_if_needed "$expected_generator"

run_step "Configuring Glasgow baseline" cmake "${cmake_args[@]}"
run_step "Building Glasgow baseline" \
  cmake --build "baselines/glasgow-subgraph-solver/build" --config Release --parallel
run_step "Checking Glasgow parity" \
  "$PYTHON_BIN" "scripts/check-glasgow-parity.py"

expected_outputs=(
  "baselines/dijkstra"
  "src/dijkstra_llm"
  "src/dijkstra_gemini"
  "src/vf3"
  "src/chatvf3"
  "src/glasgow_chatgpt"
  "src/glasgow_gemini"
  "baselines/vf3lib/bin/vf3"
  "baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver"
)

missing=0
for path in "${expected_outputs[@]}"; do
  if ! output_exists "$path"; then
    echo "Missing expected output: $path" >&2
    missing=1
  fi
done

if [[ "$missing" -ne 0 ]]; then
  echo "Build completed with missing outputs." >&2
  exit 1
fi

echo
echo "Local build complete."
