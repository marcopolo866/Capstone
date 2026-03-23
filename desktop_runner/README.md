# Desktop Benchmark Runner

Packaging inputs:

- GUI source: `desktop_runner/app.py`
- Packager scripts:
  - Windows: `desktop_runner/build_windows_exe.ps1`
  - Linux/macOS: `desktop_runner/build_unix_bundle.py`
- Cross-platform launcher: `desktop_runner/build_runner.py`
- Workflow: `.github/workflows/build-benchmark-runner.yml`

## Add More Solver Executables

1. Add the binary output path to packager scripts:
   - Windows: update `binarySpec` in `desktop_runner/build_windows_exe.ps1`
   - Linux/macOS: update `binary_spec` in `desktop_runner/build_unix_bundle.py`
2. Add the variant in `desktop_runner/app.py`:
   - `SOLVER_VARIANTS`
   - `build_binary_path_map()`
   - command wiring in `_run_solver_variant()`

The app then exposes the variant as an individual checkbox on its tab.
