# Refactor Split Structure

This document describes the behavior-preserving split of previously monolithic frontend and workflow runner scripts.

## Goals

- Reduce file size and review complexity.
- Preserve runtime behavior.
- Keep existing GitHub Actions entrypoints and environment/output contracts stable.

## What Changed

- Frontend UI script logic was split from a former monolithic file (previously `app.js`, now removed) into ordered runtime chunks under `js/app/`.
- `index.html` now loads the frontend chunks directly in a fixed order.
- `.github/scripts/run-algorithm-step.sh` is now a thin wrapper that sources ordered chunks from `.github/scripts/run-algorithm-step.d/`.
- `.github/scripts/create-result-json-step.sh` is now a thin wrapper around `.github/scripts/create-result-json-step.py`.

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

## Workflow Script Chunk Order

`run-algorithm-step.sh` sources these in order:

1. `.github/scripts/run-algorithm-step.d/01-init-inputs-and-conversion.sh`
2. `.github/scripts/run-algorithm-step.d/02-progress-reporting.sh`
3. `.github/scripts/run-algorithm-step.d/03-benchmark-and-metrics-helpers.sh`
4. `.github/scripts/run-algorithm-step.d/04-main-dispatch-and-output.sh`

Notes:

- Sourcing (not executing) preserves shared shell variables/functions and the original behavior.
- The chunk files are contiguous slices of the previous monolithic script.
- The wrapper path `.github/scripts/run-algorithm-step.sh` remains unchanged so the workflow YAML anchor still works.

## Validation

Recommended checks after changes:

```powershell
bash --noprofile --norc -n .github/scripts/run-algorithm-step.sh
bash --noprofile --norc -n .github/scripts/run-algorithm-step.d/01-init-inputs-and-conversion.sh
bash --noprofile --norc -n .github/scripts/run-algorithm-step.d/02-progress-reporting.sh
bash --noprofile --norc -n .github/scripts/run-algorithm-step.d/03-benchmark-and-metrics-helpers.sh
bash --noprofile --norc -n .github/scripts/run-algorithm-step.d/04-main-dispatch-and-output.sh
bash --noprofile --norc -n .github/scripts/create-result-json-step.sh
python -m py_compile .github/scripts/create-result-json-step.py
```

If Node is installed but not on PATH in the current shell session, use the explicit path:

```powershell
& 'C:\Program Files\nodejs\node.exe' --check js/app/01-state-progress-checks.js
```

Repeat for each `js/app/*.js` file.

## Editing Guidance

- Prefer editing the chunk files; the old top-level `app.js` file is no longer part of the repo.
- Keep wrappers thin and avoid moving logic back into wrappers.
- If you refactor chunk boundaries, rerun syntax checks and a GitHub Actions smoke run.
