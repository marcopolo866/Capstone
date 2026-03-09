# Tests

This directory now contains automated Python regression tests for the runner pipeline.

## Run Locally

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

or on Windows PowerShell:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Current Automated Coverage

- `test_generate_graphs.py`
  - Validates generator output/metadata structure.
  - Validates deterministic generation for fixed seed values.
- `test_create_result_json_step.py`
  - Validates structured metrics ingestion from `outputs/run_metrics.json`.
  - Validates fallback behavior to environment variables.

## Legacy Benchmark Scripts

- `DJ.py` and `VF3.py` are retained as ad-hoc benchmarking/plotting utilities.
- They are not part of automated CI correctness tests.
- They expect binaries to exist after running the local build script.
- Run from the `tests/` directory:

```bash
python DJ.py
python VF3.py
```
