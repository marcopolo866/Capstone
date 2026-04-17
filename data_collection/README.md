# Data Collection

This folder contains importable benchmark manifests for the headless runner.

- Manifests are plain JSON files in the same schema exported by the desktop UI.
- The headless runner only scans the top-level `.json` files in this folder.
- Batch outputs are written under `data_collection/runs/`, with one invocation folder per collection run and one subfolder per manifest inside it.

Examples:

```powershell
python scripts/benchmark-runner.py --manifest-dir data_collection --run
python desktop_runner/app.py --headless --manifest-dir data_collection --run
python scripts/benchmark-runner.py --manifest-dir data_collection --run --continue-on-error
```

Each per-manifest output folder includes the same artifacts as a normal single-manifest run, including:

- `benchmark-session.json`
- `benchmark-session.csv`
- `benchmark-datapoints.ndjson`
- `benchmark-trials.ndjson`
- plot exports such as runtime and memory PNG/SVG files
- per-trial stdout/stderr captures
