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

Manifest inventory:

- `01`-`04`: shortest-path scaling, density, via-node, and real-dataset coverage for the currently available Dijkstra-family solvers.
- `05`-`10`: original subgraph synthetic and dataset coverage updated to the current `control` variant naming scheme.
- `11`: VF3-family prompt treatment comparison across `control`, `dense`, and `sparse`.
- `12`: Glasgow-family prompt treatment comparison across `control`, `dense`, and `sparse`.
- `13`: matched VF3-vs-Glasgow comparison for the same LLM and prompt treatment.
- `14`: Dijkstra sparse-to-dense regime matrix for the currently available shortest-path LLM solvers.

Sweep summary:

- `01`: Dijkstra ER size sweep; `n=128..4096`, fixed `density=0.01`, 7 iterations.
- `02`: Dijkstra ER density sweep; fixed `n=4096`, `density=0.001..0.1`, 7 iterations.
- `03`: shortest-path-via ER size/density sweep; `n=128..4096`, `density in {0.01, 0.05}`, 7 iterations.
- `04`: Dijkstra real-dataset sweep over DIMACS USA road plus SNAP road/social graphs, 3 iterations.
- `05`: VF3 ER size sweep; `n=24..96`, fixed `density=0.05`, fixed `k=20%`, 7 iterations.
- `06`: VF3 ER phase-transition sweep; fixed `n=80`, `density in {0.05, 0.12}`, `k=5..50%`, 7 iterations.
- `07`: Glasgow ER density/size sweep; `n in {64, 96, 128}`, `density=0.01..0.12`, fixed `k=20%`, 7 iterations.
- `08`: Glasgow Barabasi-Albert density/size sweep; `n in {64, 96, 128}`, `density=0.01..0.12`, fixed `k=20%`, 7 iterations.
- `09`: VF3 real-dataset sweep over SIP, MIVIA ARG, and Practical Bigraphs, 3 iterations.
- `10`: Glasgow real-dataset sweep over SIP, MIVIA ARG, and Practical Bigraphs, 3 iterations.
- `11`: VF3 prompt-treatment matrix; all LLMs across `control/dense/sparse`, `n in {48, 64, 80, 96}`, `density in {0.03, 0.08, 0.15}`, `k in {10, 20, 30}%`, 5 iterations.
- `12`: Glasgow prompt-treatment matrix; same sweep as `11`, using LAD/Glasgow-family variants, 5 iterations.
- `13`: matched VF3-vs-Glasgow prompt-family matrix; all LLM/prompt pairs, `n in {64, 96}`, `density in {0.03, 0.08, 0.15}`, `k in {10, 20}%`, 5 iterations.
- `14`: Dijkstra ER regime matrix; `n in {512, 1024, 2048, 4096}`, `density=0.001..0.1`, 7 iterations.
