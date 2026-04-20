# Project Datasets

## Bundled Example Inputs (`data/`)

The repository currently ships deterministic sample inputs used by the UI and
local runs.

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
- Subgraph flow records equivalence diagnostics in
  `outputs/equivalence_report.jsonl`.

## Desktop Runner Dataset Catalog

The desktop runner dataset catalog lives at `desktop_runner/datasets_catalog.json`.

Current external datasets:

- `subgraph_sip_full`
  - TGZ archive with a representative LAD pattern/target pair extracted on
    demand.
- `subgraph_mivia_arg`
  - Outer ZIP archive with nested benchmark ZIPs and `.gtr` files.
  - The runner converts one representative `si2_*` non-induced subgraph pair on
    demand after download.
- `subgraph_practical_bigraphs`
  - `instances.tar.xz` archive in BigraphER string format.
  - The runner converts one representative pair from
    `instances/savannah_instances.txt` on demand after download.
- `shortest_dimacs_usa_road_d`
  - DIMACS `.gr.gz` converted to runner CSV on demand.
- `shortest_snap_*`
  - SNAP edge-list archives converted to runner CSV on demand.

Operational rules:

- Dataset downloads and conversions happen before measured solver trials.
- Conversion time and conversion memory are not included in solver runtime or
  peak-memory statistics.
- Subgraph dataset conversion normalizes graphs into simple, undirected,
  vertex-labelled, non-induced runner inputs only.
