# C++ Source Files (.cpp)
This directory contains the LLM variant solver source files used by local builds, CI workflows, and WASM builds.

## Naming Scheme
Files in this directory follow:

`[PROBLEM][LLM][FILETYPE].cpp`

Where:
- `PROBLEM` is one of `ShortestPath` or `SubgraphIsomorphism`.
- `LLM` is the variant label (for example `CHATGPT`, `GEMINI`).
- `FILETYPE` is one of:
  - `csv` for shortest-path CSV input variants.
  - `grf` for VF3/subgraph `.grf`/`.vf` variants.
  - `lad` for Glasgow `.lad` variants.

