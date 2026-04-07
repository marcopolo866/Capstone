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
- `statistical_tests` (runtime comparisons vs baseline; paired t-test, Mann-Whitney U, effect sizes, CI)
- `equivalence_check`
- `visualization`
- `subgraph_phase` (`vf3` or `glasgow` in split subgraph flow)

## Structured Metrics Source

Runner steps now emit a structured metrics snapshot:

- `outputs/run_metrics.json`

`create-result-json-step.py` consumes this file first, then falls back to environment variables for backward compatibility.

This preserves current functionality while reducing env-key coupling in workflow steps.

## Desktop Runner Session Schema

The downloadable desktop benchmark runner writes:

- `benchmark_output_YYYYMMDD_HHMMSS/benchmark-session.json`
- `benchmark_output_YYYYMMDD_HHMMSS/benchmark-session.csv`

Primary JSON fields:

- `schema_version`: currently `desktop-benchmark-v1`
- `created_at_utc`, `run_started_utc`, `run_ended_utc`
- `run_duration_ms`
- `aborted`, `timed_out`
- `completed_trials`, `planned_trials`
- `statistical_tests` (runtime comparisons vs family baseline)
- `run_config`:
  - `tab_id` (`subgraph` or `shortest_path`)
  - `selected_variants`
  - `iterations_per_datapoint`
  - `seed`
  - `stop_mode` (`threshold` or `timed`)
  - `time_limit_minutes` (timed mode)
  - `primary_variable`, `secondary_variable`
  - `var_ranges`, `fixed_values`
  - `plot3d_style`, `plot3d_variant`
- `datapoints` (list):
  - `variant_id`, `variant_label`
  - `x_value`, `y_value`
  - `runtime_median_ms`, `runtime_stdev_ms`, `runtime_samples_n`
  - `memory_median_kb`, `memory_stdev_kb`, `memory_samples_n`
  - `completed_iterations`, `requested_iterations`
  - `seeds` (iteration seeds used for that datapoint/variant)
