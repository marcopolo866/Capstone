# Pipeline Description

In addition to the browser-triggered workflow path, the repo includes a
manifest-driven headless benchmark pipeline (`scripts/benchmark-runner.py`) plus
dedicated GitHub Actions workflows for desktop packaging, validation, and
direct CLI benchmark execution.

The website has two input modes and one special combined subgraph flow. In
`premade` mode, the user uploads graph files directly, and the runner either
uses those files as-is (single-format algorithms like Dijkstra/Glasgow) or
converts them so every solver family receives the format it expects. In
`generate` mode, the runner creates graphs from `seed + iteration` logic so
each iteration is reproducible. For subgraph runs it creates both `.vf` and
vertex-labelled `.lad` encodings for the same underlying labelled undirected
pattern/target pair, retries generation with derived seeds if equivalence
fails, records structured equivalence diagnostics, and still proceeds with
attempt 10 if all retries fail so the run is never blocked. In combined
subgraph operation, phase 1 computes VF3 baseline truth and records
per-iteration baseline counts, phase 2 reuses the exact same iteration graphs
for Glasgow and LLM solvers, then all solver outputs are compared against VF3
counts and mismatch/failure metrics are written into `result.json`.

## Shared Subgraph Contract

All subgraph comparisons in this repository are intended to evaluate the same
mathematical problem:

- simple undirected graphs
- exact vertex-label matching
- no edge labels
- injective embeddings only
- non-induced semantics
  extra edges between matched target vertices are allowed
- count-all evaluation
  automorphic variants count separately and the runner compares solution counts

The `.vf` and `.lad` files used for the same iteration are two encodings of
that same labelled undirected graph pair.

```text
USER CONFIG
  -> algorithm, mode (premade|generate), iterations, warmup, sizes/density, seed
  -> dispatch starts

IF mode == premade
  -> load provided files
  -> if subgraph:
       -> ensure both formats are available (.vf and .lad)
       -> run vf<->lad equivalence check
       -> append structured equivalence record
       -> if not equivalent: keep warning + continue with selected files

IF mode == generate
  -> for each iteration i:
       -> derived_seed = base_seed + generation_counter
       -> generate graphs
       -> if algorithm == subgraph:
            -> generate pattern+target in both .vf and .lad
            -> equivalence check
            -> if equivalent: select this attempt for solver input
            -> if not equivalent: retry up to 10 attempts with new derived seeds
            -> if attempt 10 still not equivalent:
                 -> record all attempt diagnostics
                 -> mark warning + use attempt 10 anyway

SUBGRAPH COMBINED FLOW (ground truth = VF3 baseline)
  -> PHASE A (VF3):
       -> run VF3 baseline on selected .vf graphs
       -> store baseline solution counts per iteration
       -> run VF3 LLM variants on same .vf graphs
       -> compare each to baseline count
  -> PHASE B (Glasgow):
       -> reuse same iteration graph pair (matching .lad version)
       -> run Glasgow baseline first/all
       -> run Glasgow LLM variants
       -> compare each to baseline VF3 count

MATCHING + FAILURE RULES
  -> solver crash/parse failure => counted as mismatch
  -> append output line: "[Solver] failed on iteration [n]"
  -> aggregate match/mismatch/failure stats

VISUALIZATION + ARTIFACTS
  -> build visualization payload from iteration graphs used in the run
  -> write result.txt summary
  -> build result.json with:
       -> solver stats
       -> timing/memory summaries
       -> mismatch counters
       -> equivalence_check records and selected-file equivalence status
       -> warnings when selected graphs are not mathematically identical
```

## Invariants

1. Every **subgraph** solver variant in this project is expected to solve the
   same problem: count all injective embeddings of a simple undirected
   vertex-labelled pattern graph into a simple undirected vertex-labelled
   target graph under non-induced semantics.
2. Exact vertex-label equality is part of the contract. There are no edge
   labels.
3. Extra target edges between mapped vertices are allowed. Induced matching is
   not the benchmark contract.
4. For a given subgraph iteration, all solver variants must run on graph inputs
   that represent the same labelled pattern/target pair.
5. In combined subgraph runs, VF3 baseline solution count is the reference
   truth used for mismatch accounting.
6. `.vf` and `.lad` counterparts selected for the same iteration must pass the
   equivalence checker unless the retry budget is exhausted.
7. Solver failure and parser failure are never silent outcomes; they are
   counted as mismatches and reported in output text.

## Seed and Retry Derivation

1. Let `base_seed` be user-provided (or system-generated if omitted).
2. Iteration seed is `iter_seed(i) = base_seed + (i - 1)` for iteration index
   `i` starting at 1.
3. If subgraph equivalence fails on an attempt, retries use newly derived seeds
   instead of reusing the same failed seed.
4. Maximum retries for an iteration is 10 attempts.
5. If attempts `1..10` all fail equivalence, attempt 10 is still selected for
   solver execution and the failure state is recorded.

## Mode Matrix

| Mode | Execution Path | Graph Source | Solver Inputs | Equivalence Enforcement |
|---|---|---|---|---|
| `premade` + `dijkstra` | local or Actions | uploaded/provided | native dijkstra format | not applicable |
| `premade` + `vf3` | local or Actions | uploaded/provided | `.vf` (or converted equivalent) | format-compatibility conversion expected |
| `premade` + `glasgow` | local or Actions | uploaded/provided | `.lad` (or converted equivalent) | format-compatibility conversion expected |
| `premade` + `subgraph` | local or Actions | uploaded/provided + translated counterpart | VF3 gets `.vf`, Glasgow gets `.lad` | required check between original and translated pair |
| `generate` + `dijkstra` | local or Actions | generator | generated dijkstra input | not applicable |
| `generate` + `vf3` | local or Actions | generator | generated `.vf` pair | not applicable |
| `generate` + `glasgow` | local or Actions | generator | generated `.lad` pair | not applicable |
| `generate` + `subgraph` | local or Actions | generator | VF3 `.vf` pair + Glasgow `.lad` pair from same iteration seed family | required check with retry loop up to 10 |

## Failure Semantics

1. A solver process error, timeout, malformed output, or unparseable count is
   treated as a solver failure.
2. Solver failure is counted as a mismatch in aggregate comparison stats.
3. Output text includes a failure line in this exact style:
   `[Solver] failed on iteration [n]`.
4. Failure lines are emitted near the end of the output block, before final
   seed and end-to-end timing lines.
5. Failures do not terminate the whole benchmark series unless the runner
   cannot continue safely.

## Result Schema

1. `result.json` contains algorithm metadata, status, output/error text,
   inputs, timing and memory summaries, and match counters.
2. Subgraph runs include both VF3 and Glasgow stat families in shared result
   payloads.
3. `equivalence_check` records per-attempt equivalence diagnostics, selected
   attempt status, and selected-failure counts.
4. Per-iteration count diagnostics should be represented as list-style arrays
   for each solver stream.
5. Example list-style contract for a 10-iteration run:
   `solution_count_by_iteration: [c1, c2, c3, c4, c5, c6, c7, c8, c9, c10]`.
6. When selected inputs are not mathematically identical, result output
   includes an explicit warning line and structured diagnostic context.

## Visualization Guarantees

1. Pattern/target visualization is expected to trigger regardless of input
   mode, selected algorithm, and local vs Actions run location.
2. Visualization data is built from the same iteration graph files selected for
   solver execution, not from unrelated regenerated files.
3. For combined subgraph flow, visualization corresponds to the shared
   iteration graph family used by both VF3 and Glasgow phases.
4. If solver output is missing, visualization still renders graph structure and
   marks `no_solutions` where appropriate.

## Parity Gates

1. CI and local build paths both execute the same Glasgow parity gate to
   enforce behavior parity.
2. Parity gates verify separate LLM source files and check baseline-vs-LLM
   solution-count agreement on deterministic test input.
3. Parity gates emit hash diagnostics for traceability of source and built
   binaries.
4. A parity gate failure should fail the build step so mismatched binaries are
   not published as trusted artifacts.

## Known Ambiguities and Resolution Rules

1. Mathematical equivalence must include node-count consistency, exact
   vertex-label agreement, and simple undirected edge-set equality.
2. Duplicate edges, self-loops, or asymmetric adjacency serialization must be
   normalized before equivalence comparison.
3. LAD format detection can be ambiguous between standard and vertex-labelled
   variants; parser behavior should be explicitly documented.
4. If parser interpretations differ between solver implementations,
   equivalence may pass while counts still diverge; this requires
   parser-contract tests.
5. When retries exhaust and non-equivalent graphs are used, downstream
   comparisons remain useful operational telemetry but not strict correctness
   proof.
