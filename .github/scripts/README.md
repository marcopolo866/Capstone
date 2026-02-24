# GitHub Script Layout

This folder contains GitHub Actions runtime scripts used by `.github/workflows/run-algorithm.yml`.

## Entry Points (stable paths)

- `run-algorithm-step.sh`
- `create-result-json-step.sh`

These paths are referenced by workflow anchors and should remain stable unless the workflow is updated at the same time.

## Internal Structure

- `run-algorithm-step.sh` is a wrapper that sources ordered chunks from `run-algorithm-step.d/`
- `create-result-json-step.sh` is a wrapper that invokes `create-result-json-step.py`

## Why Wrappers

- Keeps workflow YAML small and readable
- Preserves original shell environment/output behavior
- Allows chunking without changing the workflow anchor names

## Important Invariants

- Do not change GitHub Actions output variable names without updating the workflow and UI/result parsing code.
- Preserve source order in `run-algorithm-step.sh` unless you have verified there are no variable/function ordering dependencies.
- `create-result-json-step.py` consumes environment variables set by workflow steps; preserve names and defaults.

## Validation

Run syntax checks after changes:

```powershell
bash --noprofile --norc -n .github/scripts/run-algorithm-step.sh
bash --noprofile --norc -n .github/scripts/create-result-json-step.sh
python -m py_compile .github/scripts/create-result-json-step.py
```
