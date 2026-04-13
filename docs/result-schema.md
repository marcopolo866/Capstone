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
- `benchmark_output_YYYYMMDD_HHMMSS/benchmark-datapoints.ndjson`
- `benchmark_output_YYYYMMDD_HHMMSS/benchmark-trials.ndjson`
- `benchmark_output_YYYYMMDD_HHMMSS/benchmark-manifest.json`

Primary JSON fields:

- `schema_version`: currently `desktop-benchmark-v2`
- `created_at_utc`, `run_started_utc`, `run_ended_utc`
- `run_duration_ms`
- `completed_trials`, `planned_trials`
- `manifest_path`
- `trials_path`
- `dataset_selection`
- `statistical_tests` (runtime comparisons vs family baseline)
- `run_config`:
  - `preset`
  - `tab_id` (`subgraph` or `shortest_path`)
  - `input_mode` (`independent` or `datasets`)
  - `selected_variants_requested`
  - `selected_variants`
  - `injected_baselines`
  - `selected_datasets`
  - `iterations_per_datapoint`
  - `seed`
  - `primary_variable`, `secondary_variable`
  - `var_ranges`, `fixed_values`
  - `solver_timeout_seconds`
  - `failure_policy`
  - `retry_failed_trials`
  - `outlier_filter`
- `datapoints` (list):
  - `variant_id`, `variant_label`
  - `dataset_id`, `dataset_name`
  - `x_value`, `y_value`
  - `runtime_median_ms`, `runtime_stdev_ms`, `runtime_samples_n`
  - `memory_median_kb`, `memory_stdev_kb`, `memory_samples_n`
  - `completed_iterations`, `requested_iterations`
  - `seeds` (iteration seeds used for that datapoint/variant)
  - `answer_kind`
  - `path_length_median`

Trial NDJSON rows are standardized across solver families and include:

- `status`
- `point_index`, `iteration_index`, `seed`
- `variant_id`, `family`
- `command`, `cwd`
- `runtime_ms`, `peak_kb`, `return_code`
- `stdout_path`, `stderr_path`
- `normalized_result`
