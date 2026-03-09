# Project Datasets

## Bundled Example Inputs (`data/`)

The repository currently ships deterministic sample inputs used by the UI and local runs.

| Problem Area | File(s) | Format | Notes |
|---|---|---|---|
| Dijkstra | `dijkstra_sample.csv`, `dijkstra1.csv`, `dijkstra_weighted_graph_1.csv`, `dijkstra_weighted_graph_2.csv` | CSV | Weighted edges with optional start/target comment line |
| VF3 | `VF3_SUB_20.grf`, `VF3_20.grf`, `VF3_SUB_400.grf`, `VF3_400.grf` | GRF/VF style | Pattern/target graph pairs |
| Glasgow | `GLAS_SUB_5.lad`, `GLAS_5.lad`, `glasgowpattern1.lad`, `glasgowtarget1.lad` | LAD | Pattern/target graph pairs |

## Generated Inputs

When input mode is `generate`, graphs are produced by:

- `utilities/generate_graphs.py`

Determinism contract:

- Fixed `(algorithm, n, k, density, seed)` must generate identical graph files.
- Subgraph flow records equivalence diagnostics in `outputs/equivalence_report.jsonl`.

## Notes for Benchmark Reporting

If you use additional external datasets for final reporting, record:

- dataset source URL
- license/usage terms
- exact commit/hash or download date
- preprocessing steps

This keeps performance/correctness claims reproducible.
