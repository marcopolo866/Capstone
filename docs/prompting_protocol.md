# Prompting Protocol for LLM Graph Algorithm Evaluation

**Version:** 1.3  
**Date:** 04/24/2026

This document outlines the standardized methodology for interacting with the
LLM so the generated solver variants line up with the benchmark pipeline that
ships in this repository.

## 1.0 LLM Configuration

- **Model:** GPT-4-Turbo (via the standard ChatGPT web interface)
- **Temperature:** 0.7
- **Conversation Context:** Each problem family is handled in a fresh thread so
  no cross-problem implementation context leaks between tasks.

## 2.0 Prompting Strategy

Our interaction with the LLM follows a three-stage process:

1. **Seed Prompt:** generate the initial C++ solution.
2. **Remediation Prompts:** fix compile/runtime correctness issues.
3. **Optimization Prompts:** improve performance after correctness is
   established.

## 3.0 Seed Prompt Templates

### 3.1 Seed Prompt Family: Single-Pair Shortest Path

The active shortest-path experiment now uses two dedicated prompt files:

- [prompts/prompt_dijkstra.txt](prompts/prompt_dijkstra.txt)
- [prompts/prompt_sp_via.txt](prompts/prompt_sp_via.txt)

Both prompts are written directly against the current benchmark pipeline
contract and compile chain:

1. Use **standard C++20 only**.
2. Do **not** rely on non-portable headers such as `<bits/stdc++.h>`.
3. Return output in a format the runner and correctness scripts already parse.
4. Avoid runtime/debug chatter in the normal success path.

The two shortest-path prompt files differ by mathematical contract:

- `prompt_dijkstra.txt`
  - Plain **single-pair shortest path** on a **directed weighted** graph.
  - CLI contract:
    `./solver <input_file>`
  - Input format:
    `# start=<label> target=<label>` plus `source,target,weight` rows.
  - Required first-line output:
    `<distance>; <path labels...>` when reachable, or `INF; (no path)` if
    unreachable.

- `prompt_sp_via.txt`
  - **Single-pair shortest path through a required intermediate node** on a
    **directed weighted** graph.
  - CLI contract:
    `./solver <input_file> <via_label>`
  - Input format:
    `# start=<label> target=<label> via=<label>` plus
    `source,target,weight` rows, with the runner also passing the via label on
    the command line.
  - Required first-line output:
    `<distance>; <path labels...>` when reachable, or `INF; (no path)` if
    unreachable.

### 3.2 Seed Prompt Family: Subgraph Matching

The active subgraph experiment now uses six dedicated prompt files with the
naming scheme:

`prompt_<family>_<regime>.txt`

Where:

- `family` is `vf3` or `glasgow`
- `regime` is `sparse`, `dense`, or `control`

Current files:

- [prompts/prompt_vf3_sparse.txt](prompts/prompt_vf3_sparse.txt)
- [prompts/prompt_vf3_dense.txt](prompts/prompt_vf3_dense.txt)
- [prompts/prompt_vf3_control.txt](prompts/prompt_vf3_control.txt)
- [prompts/prompt_glasgow_sparse.txt](prompts/prompt_glasgow_sparse.txt)
- [prompts/prompt_glasgow_dense.txt](prompts/prompt_glasgow_dense.txt)
- [prompts/prompt_glasgow_control.txt](prompts/prompt_glasgow_control.txt)

All six prompts intentionally share the same mathematical contract. They differ
only by solver-family input format framing and by performance steering:

1. Solve **simple undirected vertex-labelled** subgraph matching.
2. Use **non-induced** semantics:
   extra edges between matched target vertices are allowed.
3. Count **all** injective embeddings.
4. Do **not** stop after the first solution.
5. Do **not** apply symmetry breaking; automorphic variants count separately.
6. Match vertex labels exactly. There are no edge labels.
7. Accept the current family-specific benchmark input format:
   VF3-family prompts use the VF-style `.vf` / `.grf` text format, and
   Glasgow-family prompts use vertex-labelled `.lad`.
8. Print a parseable integer solution count.

The six prompt files differ as follows:

- `prompt_vf3_sparse.txt`: VF3 format + sparse structured regime hint
- `prompt_vf3_dense.txt`: VF3 format + dense irregular regime hint
- `prompt_vf3_control.txt`: VF3 format + no regime-specific hint
- `prompt_glasgow_sparse.txt`: Glasgow LAD format + sparse structured regime hint
- `prompt_glasgow_dense.txt`: Glasgow LAD format + dense irregular regime hint
- `prompt_glasgow_control.txt`: Glasgow LAD format + no regime-specific hint

## 4.0 Follow-up Prompt Templates

- **For Remediation:**  
  `The previous code failed to compile with the error: [paste full compiler error here]. Please fix the code to resolve this specific error.`
- **For Optimization:**  
  `The current implementation is correct but may be slow. Can you refactor the code to [describe a specific change] and explain the performance trade-offs?`
