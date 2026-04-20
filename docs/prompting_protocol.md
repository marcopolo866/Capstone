# Prompting Protocol for LLM Graph Algorithm Evaluation

**Version:** 1.2  
**Date:** 04/20/2026

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

The active shortest-path experiment now uses three dedicated prompt files with
the naming scheme:

`prompt_dijkstra_<regime>.txt`

Where `regime` is `sparse`, `dense`, or `control`.

Current files:

- [prompt_dijkstra_sparse.txt](prompt_dijkstra_sparse.txt)
- [prompt_dijkstra_dense.txt](prompt_dijkstra_dense.txt)
- [prompt_dijkstra_control.txt](prompt_dijkstra_control.txt)

All three prompts intentionally share the same shortest-path contract. They
differ only by performance steering:

1. Solve **single-pair shortest path** on a **directed weighted** graph.
2. Edge weights are **nonnegative integers**.
3. Accept the benchmark CSV format with:
   `# start=<label> target=<label>` followed by
   `source,target,weight` rows.
4. Return the **exact** shortest-path distance.
5. Treat reverse arcs as absent unless explicitly present in the CSV.
6. Handle duplicate directed arcs correctly; the minimum repeated weight should
   determine the effective cost.
7. Print a parseable shortest-path result that the runner can normalize.
8. The preferred output format is:
   `<distance>; <path labels...>` when reachable, or `INF` if unreachable.

The three prompt files differ as follows:

- `prompt_dijkstra_sparse.txt`: shortest-path CSV format + sparse structured
  regime hint
- `prompt_dijkstra_dense.txt`: shortest-path CSV format + dense irregular
  regime hint
- `prompt_dijkstra_control.txt`: shortest-path CSV format + no regime-specific
  hint

### 3.2 Seed Prompt Family: Subgraph Matching

The active subgraph experiment now uses six dedicated prompt files with the
naming scheme:

`prompt_<family>_<regime>.txt`

Where:

- `family` is `vf3` or `glasgow`
- `regime` is `sparse`, `dense`, or `control`

Current files:

- [prompt_vf3_sparse.txt](prompt_vf3_sparse.txt)
- [prompt_vf3_dense.txt](prompt_vf3_dense.txt)
- [prompt_vf3_control.txt](prompt_vf3_control.txt)
- [prompt_glasgow_sparse.txt](prompt_glasgow_sparse.txt)
- [prompt_glasgow_dense.txt](prompt_glasgow_dense.txt)
- [prompt_glasgow_control.txt](prompt_glasgow_control.txt)

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
