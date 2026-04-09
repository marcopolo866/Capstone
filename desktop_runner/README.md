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

## External Dataset Catalog

- Catalog file: `desktop_runner/datasets_catalog.json`
- Local cache folder (auto-created, outside repo by default):
  - Windows: `%LOCALAPPDATA%\\CapstoneBenchmarkRunner\\datasets`
  - macOS: `~/Library/Application Support/CapstoneBenchmarkRunner/datasets`
  - Linux: `${XDG_DATA_HOME:-~/.local/share}/capstone-benchmark-runner/datasets`
  - Optional override: set `CAPSTONE_DATASETS_DIR`

The desktop UI now includes an **Independent Variables / Datasets** selector.  
When the **Datasets** tab is active, the runner uses selected dataset rows from the catalog (download + conversion status is tracked per row).

To add/edit datasets for future users:

1. Open `desktop_runner/datasets_catalog.json`.
2. Add or edit a row under `datasets` with:
   - `dataset_id`, `name`, `tab_id` (`subgraph` or `shortest_path`)
   - metadata fields (`source`, `source_url`, `raw_format`, `description`, size/count estimates)
   - `download` block (`single_file`, `multi_file`, or `manual_request`)
   - `prepare` block (converter type and file/member references, or `download_only` / `manual_request`)
3. Restart the desktop runner to reload the catalog.

Optional CLI converter/downloader:

```bash
python scripts/prepare-datasets.py --list
python scripts/prepare-datasets.py --id subgraph_sip_full
python scripts/prepare-datasets.py --all
```
