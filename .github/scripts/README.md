# GitHub Script Layout

This folder contains GitHub Actions runtime scripts used by `.github/workflows/run-algorithm.yml`.

## Entry Points

- `run-algorithm-dynamic.py`
- `create-result-json-step.py`

These paths are referenced directly by workflow `run:` commands.

## Important Invariants

- Do not change GitHub Actions output variable names without updating the workflow and UI/result parsing code.
- `run-algorithm-dynamic.py` is responsible for writing `outputs/run_metrics.json`.
- `create-result-json-step.py` consumes environment variables set by workflow steps; preserve names and defaults.

## Validation

Run syntax checks after changes:

```powershell
python -m py_compile .github/scripts/run-algorithm-dynamic.py
python -m py_compile .github/scripts/create-result-json-step.py
```
