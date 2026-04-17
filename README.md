# Capstone Algorithm Benchmark Runner

This repository benchmarks baseline vs LLM-generated C++ implementations for:

- Dijkstra shortest path
- VF3 subgraph isomorphism
- Glasgow subgraph solver variants
- Combined subgraph flow (VF3 + Glasgow + LLM comparisons on equivalent inputs)

The project provides:

- A browser UI (`index.html`) for local WASM runs and GitHub Actions runs
- A manifest-driven headless benchmark CLI (`scripts/benchmark-runner.py`)
- Native build scripts for baseline + LLM binaries
- Workflow-driven benchmark execution and artifact generation
- Visualization and result export (`outputs/result.json`, `outputs/visualization.json`)
- Downloadable desktop benchmark runner artifacts for Windows, macOS, and Linux

## Quick Start

1. Build native binaries:
   - Native solvers: `make build-local`
   - Desktop runner package: `make build-runner`
   - Both: `make build-all`
   - Regression tests: `make test`
   - Cleanup: `make clean`
   - Optional direct script path: `python scripts/build-local.py --backend sh --validation full`
   - Optional CMake path: `cmake -S . -B build/cmake && cmake --build build/cmake`
   - Windows runtime note: the desktop runner and headless CLI automatically prepend `C:\msys64\mingw64\bin` and `C:\msys64\usr\bin` when those directories exist.
2. Open `index.html` from a local static server.
3. Connect to a repository/branch in the UI.
4. Select algorithm + input mode (`premade` or `generate`).
5. Run:
   - `Standard Run (GitHub Actions)` for remote benchmark artifacts.
   - `Run Locally (WebAssembly)` for browser-local execution.
6. (Optional) Download the desktop benchmark runner from the UI button:
   - `Download Benchmark Runner` (latest successful artifact for your OS)

Headless CLI example:

```bash
python scripts/benchmark-runner.py \
  --run \
  --preset smoke \
  --tab-id subgraph \
  --input-mode independent \
  --variants vf3_chatgpt \
  --n-values 64 \
  --density-values 0.05 \
  --k-values 10
```

Headless Data Collection batch example:

```bash
python scripts/benchmark-runner.py --manifest-dir data_collection --run
```

For detailed setup/run instructions, see [docs/quickstart.md](docs/quickstart.md).

## Repository Map

- `js/app/`: frontend runtime chunks
- `.github/workflows/`: CI/build/run workflows
- `.github/scripts/`: workflow runtime scripts
- `utilities/generate_graphs.py`: deterministic graph generation
- `scripts/`: local build and parity tooling
- `desktop_runner/`: downloadable desktop benchmark runner source + packager
- `tests/`: automated regression tests
- `wasm/`: prebuilt wasm modules + manifest for local mode

## Regression Tests

Run:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Documentation

- [docs/quickstart.md](docs/quickstart.md)
- [docs/datasets.md](docs/datasets.md)
- [docs/result-schema.md](docs/result-schema.md)
- [docs/prompting_protocol.md](docs/prompting_protocol.md)
- [docs/pipeline-description.md](docs/pipeline-description.md)
