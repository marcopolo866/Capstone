# Result Schema (Operational)

Primary artifact:

- `outputs/result.json`

## Top-Level Fields

- `algorithm`: algorithm id (`dijkstra`, `vf3`, `glasgow`, `subgraph`)
- `timestamp`: UTC timestamp string
- `status`: `success` or `error`
- `output`: runner stdout summary text
- `error`: runner error text (if any)
- `request_id`: UI/workflow request correlation id
- `iterations`, `warmup`
- `run_duration_ms`
- `inputs`: user/generator input metadata

Optional sections:

- `timings_ms`, `timings_ms_stdev`
- `memory_kb`, `memory_kb_stdev`
- `match_counts`
- `equivalence_check`
- `visualization`
- `subgraph_phase` (`vf3` or `glasgow` in split subgraph flow)

## Structured Metrics Source

Runner steps now emit a structured metrics snapshot:

- `outputs/run_metrics.json`

`create-result-json-step.py` consumes this file first, then falls back to environment variables for backward compatibility.

This preserves current functionality while reducing env-key coupling in workflow steps.
