# Documentation Index

This folder contains project documentation for setup, workflow behavior, and
research protocol.

## Core Documents

- [quickstart.md](quickstart.md)
  - Build/run instructions for local, headless CLI, GitHub Actions, and
    desktop runner download.
- [datasets.md](datasets.md)
  - Dataset inventory, on-demand conversion rules, and file format notes.
- [result-schema.md](result-schema.md)
  - `outputs/result.json`, desktop session artifacts, and normalized
    trial/datapoint schema notes.
- [prompting_protocol.md](prompting_protocol.md)
  - LLM prompting process used in this capstone.
- [prompt_dijkstra_sparse.txt](prompt_dijkstra_sparse.txt)
  - Dijkstra CSV-format shortest-path seed prompt tuned for sparse structured
    graph regimes.
- [prompt_dijkstra_dense.txt](prompt_dijkstra_dense.txt)
  - Dijkstra CSV-format shortest-path seed prompt tuned for dense irregular
    graph regimes.
- [prompt_dijkstra_control.txt](prompt_dijkstra_control.txt)
  - Dijkstra CSV-format shortest-path seed prompt with the shared contract but
    no regime-specific hint.
- [prompt_vf3_sparse.txt](prompt_vf3_sparse.txt)
  - VF3-format subgraph seed prompt tuned for sparse structured graph regimes.
- [prompt_vf3_dense.txt](prompt_vf3_dense.txt)
  - VF3-format subgraph seed prompt tuned for dense irregular graph regimes.
- [prompt_vf3_control.txt](prompt_vf3_control.txt)
  - VF3-format subgraph seed prompt with the shared contract but no
    regime-specific hint.
- [prompt_glasgow_sparse.txt](prompt_glasgow_sparse.txt)
  - Glasgow LAD-format subgraph seed prompt tuned for sparse structured graph
    regimes.
- [prompt_glasgow_dense.txt](prompt_glasgow_dense.txt)
  - Glasgow LAD-format subgraph seed prompt tuned for dense irregular graph
    regimes.
- [prompt_glasgow_control.txt](prompt_glasgow_control.txt)
  - Glasgow LAD-format subgraph seed prompt with the shared contract but no
    regime-specific hint.
- [refactor-split-structure.md](refactor-split-structure.md)
  - Frontend/workflow split history and invariants.

## Related Root Docs

- [pipeline-description.md](pipeline-description.md)
- [../README.md](../README.md)

## Remediation Ledger

Spreadsheet link used by the team:

- https://docs.google.com/spreadsheets/d/1hdHh30pgJRnWd4VIoceJsj7AAvxvCbOJsMZ1v115Ids/edit?usp=sharing

Suggested columns:

- `fix_id`
- `timestamp`
- `problem_area`
- `file_path`
- `lines_changed`
- `time_spent_min`
- `category`
- `rationale`
- `impact_on_correctness`
- `impact_on_performance`
