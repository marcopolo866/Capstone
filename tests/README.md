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
- `tests/cpp/graph_oracle_tests.cpp` (via CMake/CTest)
  - C++ edge-case checks for shortest-path and subgraph mapping oracles.
  - Property-based randomized checks for path optimality and witness mapping validity.

## Legacy Benchmark Scripts

- `DJ.py` and `VF3.py` are retained as ad-hoc benchmarking/plotting utilities.
- They are not part of automated CI correctness tests.
- They expect binaries to exist after running the local build script.
- Run from the `tests/` directory:

```bash
python DJ.py
python VF3.py
```

## C++ Oracle Tests (CMake)

```bash
cmake -S . -B build/cmake -DCAPSTONE_BUILD_SOLVERS=OFF
cmake --build build/cmake --target capstone_graph_oracle_tests
ctest --test-dir build/cmake -R capstone_graph_oracle_tests --output-on-failure
```
