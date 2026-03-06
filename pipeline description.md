# Pipeline Description

The website has two input modes and one special combined subgraph flow. In `premade` mode, the user uploads graph files directly, and the runner either uses those files as-is (single-format algorithms like Dijkstra/Glasgow) or converts them so every solver family receives the format it expects (VF3 uses `.vf`, Glasgow uses `.lad`). In `generate` mode, the runner creates graphs from `seed + iteration` logic so each iteration is reproducible; for subgraph runs it creates both `.vf` and `.lad` encodings for mathematically equivalent pattern/target pairs, retries generation with derived seeds if equivalence fails, records the structured equivalence diagnostics, and still proceeds with attempt 10 if all retries fail so the run is never blocked. In combined subgraph operation, phase 1 computes VF3 baseline truth and records per-iteration baseline counts, phase 2 reuses the exact same iteration graphs for Glasgow and LLM solvers, then all solver outputs are compared against VF3 counts and mismatch/failure metrics are written into `result.json`. Visualizer graph payloads are produced from the same iteration inputs so displayed pattern/target graphs correspond to what solvers executed, and failures are tracked as mismatches plus explicit failure messages in the output text block.

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
       -> run VF3 ChatGPT + VF3 Gemini on same .vf graphs
       -> compare each to baseline count
  -> PHASE B (Glasgow):
       -> reuse same iteration graph pair (matching .lad version)
       -> run Glasgow baseline first/all
       -> run Glasgow ChatGPT + Glasgow Gemini
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
