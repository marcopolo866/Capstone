# External Dataset Shortlist (Subgraph)

## Tier 1: Use Immediately (Direct format compatibility)

1. SIP Benchmarks (Solnon)
- URL: https://perso.citi-lab.fr/csolnon/SIP.html
- Archive: http://perso.citi-lab.fr/csolnon/newSIPbenchmarks.tgz
- File type observed: LAD-style adjacency files named `pattern` / `target` (no extension)
- Compatibility: Glasgow LLM binaries (`src/glasgow_chatgpt.exe`, `src/glasgow_gemini.exe`, `src/glasgow_claude.exe`) run directly.

2. VF3/MIVIA sample graphs (via vf3lib test corpus)
- URL: https://github.com/MiviaLab/vf3lib/tree/master/test
- Sample files used: 
  - https://raw.githubusercontent.com/MiviaLab/vf3lib/master/test/bvg1.sub.grf
  - https://raw.githubusercontent.com/MiviaLab/vf3lib/master/test/bvg1.grf
- File type observed: `.grf`
- Compatibility: VF3 LLM binaries (`src/vf3_chatgpt.exe`, `src/vf3_claude.exe`) run directly.

## Tier 2: Valuable but Requires Conversion/Adapter

3. DIMACS graph instances
- Sample URL: https://mat.tepper.cmu.edu/COLOR/instances/queen5_5.col
- File type observed: `.col` (DIMACS)
- Compatibility: Not directly accepted by strict LLM binaries in this repo.
- Notes: Convert to LAD/GRF before use.

4. SNAP network datasets
- Sample URL: https://snap.stanford.edu/data/ca-GrQc.txt.gz
- File type observed: edge-list `.txt`
- Compatibility: Not directly accepted by strict LLM binaries in this repo.
- Notes: Convert edge list to LAD/GRF and optionally add labels.

5. Glasgow solver test-instances
- URL: https://github.com/ciaranm/glasgow-subgraph-solver/tree/master/test-instances
- Sample files used:
  - https://raw.githubusercontent.com/ciaranm/glasgow-subgraph-solver/master/test-instances/c3.csv
  - https://raw.githubusercontent.com/ciaranm/glasgow-subgraph-solver/master/test-instances/trident.csv
- File type observed: `.csv`
- Compatibility: Not directly accepted by strict LAD-only LLM Glasgow binaries in this repo.
- Notes: Convert/reformat to LAD before use in current desktop runner flow.

## Local evidence
- Compatibility run artifacts:
  - `outputs/dataset_compatibility_report.md`
  - `outputs/dataset_compatibility_report.json`
