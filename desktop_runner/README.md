# Desktop Benchmark Runner

Packaging inputs:

- GUI source: `desktop_runner/app.py`
- Packager scripts:
  - Windows: `desktop_runner/build_windows_exe.ps1`
  - Linux/macOS: `desktop_runner/build_unix_bundle.py`
- Cross-platform launcher: `desktop_runner/build_runner.py`
- Workflow: `.github/workflows/build-benchmark-runner.yml`

## Add More Solver Executables

1. Keep baselines hard-wired (`dijkstra_baseline`, `vf3_baseline`, `glasgow_baseline`).
2. Add LLM source files under `src/` using the naming pattern:
   - `[ShortestPath][LLM][csv].cpp`
   - `[SubgraphIsomorphism][LLM][grf].cpp`
   - `[SubgraphIsomorphism][LLM][lad].cpp`
3. Build binaries (`scripts/build-local.py`) so each discovered variant has an executable at `src/<family>_<llm>`.

The desktop runner auto-discovers LLM variants from `scripts/solver_discovery.py` (or bundled binaries as fallback) and shows them as individual checkboxes.
