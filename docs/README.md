# Documentation Index

This folder contains project documentation for setup, workflow behavior, and research protocol.

## Core Documents

- [quickstart.md](quickstart.md)
  - Build/run instructions for local and GitHub Actions paths.
- [datasets.md](datasets.md)
  - Dataset inventory and file format notes.
- [result-schema.md](result-schema.md)
  - `outputs/result.json` structure and metrics source notes.
- [prompting_protocol.md](prompting_protocol.md)
  - LLM prompting process used in this capstone.
- [refactor-split-structure.md](refactor-split-structure.md)
  - Frontend/workflow split history and invariants.

## Related Root Docs

- [pipeline-description.md](pipeline-description.md)
- [../local-compilation-command.md](../local-compilation-command.md)
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
