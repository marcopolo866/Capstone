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
./scripts/build-local.ps1
```

Linux/macOS:

```bash
bash scripts/build-local.sh
```

Both scripts:

- initialize submodules
- build baseline + LLM binaries
- run Glasgow parity checks

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
