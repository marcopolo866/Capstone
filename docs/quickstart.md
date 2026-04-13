# Quick Start

## Prerequisites

- Git
- Python 3
- C++ toolchain (`g++`, `make`, `cmake`)
- Git submodules enabled

Optional:

- Node (syntax-check frontend chunks)

## 1. Build Native Binaries

Windows (PowerShell):

```powershell
python scripts/build-local.py --backend sh --validation full
```

Linux/macOS:

```bash
python scripts/build-local.py --backend sh --validation full
```

Both scripts:

- initialize submodules
- build baseline + LLM binaries
- run Glasgow parity checks
- run subgraph count-correctness checks

Variants:

- fast smoke build: add `--validation fast`
- AddressSanitizer: add `--sanitizer address`
- UBSan: add `--sanitizer undefined`

## 1b. Optional CMake Build Path (C++20)

```bash
cmake -S . -B build/cmake
cmake --build build/cmake --parallel
```

The root `CMakeLists.txt` enforces `CMAKE_CXX_STANDARD=20` and exposes CTest targets for oracle/property tests.

## 2. Run Automated Regression Tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## 3. Run the Web UI

Serve the repository root with any static server, then open `index.html`.

Example:

```bash
python -m http.server 8080
```

Open:

- `http://localhost:8080/index.html`

## 4. Use the UI

1. Choose algorithm (`dijkstra`, `vf3`, `glasgow`, `subgraph`).
2. Choose input mode:
   - `premade`: pick files from repo `data/`.
   - `generate`: use deterministic generator parameters.
3. Choose run mode:
   - `Standard Run (GitHub Actions)`: remote workflow run + artifacts.
   - `Run Locally (WebAssembly)`: browser-local execution with wasm modules.

## 4b. Run The Headless Benchmark CLI

Independent-input example:

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

Dataset example:

```bash
python scripts/benchmark-runner.py \
  --run \
  --preset smoke \
  --tab-id subgraph \
  --input-mode datasets \
  --variants vf3_chatgpt \
  --datasets subgraph_sip_full
```

Manifest workflow:

```bash
python scripts/benchmark-runner.py --write-manifest benchmarks/smoke.json --preset smoke --tab-id subgraph --variants vf3_chatgpt --n-values 64 --density-values 0.05 --k-values 10
python scripts/benchmark-runner.py --manifest benchmarks/smoke.json --run
```

GUI workflow:

- Configure the benchmark in the desktop runner.
- Keep `Stop Mode` set to `Threshold`.
- Click `Export Manifest`.
- Later, use `Import Manifest` in the GUI to restore the same setup.
- Run it later with:

```bash
python scripts/benchmark-runner.py --manifest path/to/exported-manifest.json --run
```

## 5. Build WASM Modules (if local wasm is missing)

Run GitHub Actions workflow:

- `.github/workflows/build-wasm.yml`

Expected outputs:

- `wasm/*.js`
- `wasm/*.wasm`
- `wasm/manifest.json`

## 6. Common Validation Commands

Frontend chunk syntax:

```bash
node --check js/app/01-state-progress-checks.js
node --check js/app/02-inputs-generator-ui.js
node --check js/app/03-generator-estimation.js
node --check js/app/04-local-wasm-and-local-runner.js
node --check js/app/05-github-workflow-runner.js
node --check js/app/06-results-and-charts.js
node --check js/app/07-visualization-api-bootstrap.js
```

Workflow script syntax:

```bash
python -m py_compile .github/scripts/run-algorithm-dynamic.py
python -m py_compile .github/scripts/create-result-json-step.py
```

## 7. Desktop Benchmark Runner (Windows/macOS/Linux)

Users can download an OS-specific desktop benchmark runner artifact from the web UI:

1. Open `index.html` in the browser.
2. Enter `owner`, `repo`, and a token with Actions read access.
3. Click `Download Benchmark Runner` near `Connect to Repository`.

The button pulls the latest successful artifact from:

- workflow: `.github/workflows/build-benchmark-runner.yml`
- artifact name: `benchmark-runner-windows`, `benchmark-runner-macos`, or `benchmark-runner-linux` (based on your browser OS)

The downloaded artifact zip contains the packaged desktop runner plus bundled solver binaries for that platform.

Trusted packaging and validation workflows:

- `.github/workflows/build-benchmark-runner.yml`: fully validated packaged artifacts
- `.github/workflows/benchmark-cli.yml`: manifest-driven headless benchmark workflow
