# Desktop Benchmark Runner

Windows packaging inputs:

- GUI source: `desktop_runner/app.py`
- Packager script: `desktop_runner/build_windows_exe.ps1`
- Workflow: `.github/workflows/build-benchmark-runner-windows.yml`

## Add More Solver Executables

1. Add the binary output path to `desktop_runner/build_windows_exe.ps1`:
   - `binaryFiles` (existence checks)
   - `--add-binary` list (bundle into `binaries/`)
2. Add the variant in `desktop_runner/app.py`:
   - `SOLVER_VARIANTS`
   - `build_binary_path_map()`
   - command wiring in `_run_solver_variant()`

The app then exposes the variant as an individual checkbox on its tab.
