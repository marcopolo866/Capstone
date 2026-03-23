# Refactor Split Structure

This document describes the behavior-preserving split of previously monolithic frontend and workflow runner scripts.

## Goals

- Reduce file size and review complexity.
- Preserve runtime behavior.
- Keep GitHub Actions output contracts stable.

## What Changed

- Frontend UI script logic was split from a former monolithic file (previously `app.js`, now removed) into ordered runtime chunks under `js/app/`.
- `index.html` now loads the frontend chunks directly in a fixed order.
- GitHub workflow execution now calls Python entrypoints directly:
  - `.github/scripts/run-algorithm-dynamic.py`
  - `.github/scripts/create-result-json-step.py`

## Frontend Runtime Chunk Order

`index.html` must load these in this exact order because they share globals:

1. `js/app/01-state-progress-checks.js`
2. `js/app/02-inputs-generator-ui.js`
3. `js/app/03-generator-estimation.js`
4. `js/app/04-local-wasm-and-local-runner.js`
5. `js/app/05-github-workflow-runner.js`
6. `js/app/06-results-and-charts.js`
7. `js/app/07-visualization-api-bootstrap.js`

Notes:

- These files are contiguous slices of the original script, not isolated ES modules.
- They intentionally share global state/functions.
- Do not reorder them unless you also refactor globals and event wiring.

## Workflow Runtime Scripts

`run-algorithm.yml` invokes:

1. `.github/scripts/run-algorithm-dynamic.py`
2. `.github/scripts/create-result-json-step.py`

Notes:

- `run-algorithm-dynamic.py` writes `outputs/run_metrics.json`.
- `create-result-json-step.py` consumes that file first and falls back to environment values.

## Validation

Recommended checks after changes:

```powershell
python -m py_compile .github/scripts/run-algorithm-dynamic.py
python -m py_compile .github/scripts/create-result-json-step.py
```

If Node is installed but not on PATH in the current shell session, use the explicit path:

```powershell
& 'C:\Program Files\nodejs\node.exe' --check js/app/01-state-progress-checks.js
```

Repeat for each `js/app/*.js` file.

## Editing Guidance

- Prefer editing the chunk files; the old top-level `app.js` file is no longer part of the repo.
- If you refactor runtime script boundaries, rerun syntax checks and a GitHub Actions smoke run.
