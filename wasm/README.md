# WebAssembly (Local Run)

This folder contains prebuilt WebAssembly modules used by the **Run Locally (WebAssembly)** option in `index.html`.

The WASM builds include allocator telemetry (`wasm/allocator_telemetry.cpp`) so local memory stats can report per-run allocator peak usage when the telemetry exports are present.

## Build / Update

Run the GitHub Actions workflow **Build WASM Modules** (`.github/workflows/build-wasm.yml`) to regenerate (it also runs automatically on pushes to `main`):

- `wasm/vf3_baseline.js` + `wasm/vf3_baseline.wasm`
- `wasm/vf3_gemini.js` + `wasm/vf3_gemini.wasm`
- `wasm/vf3_chatgpt.js` + `wasm/vf3_chatgpt.wasm`
- `wasm/dijkstra_baseline.js` + `wasm/dijkstra_baseline.wasm`
- `wasm/dijkstra_llm.js` + `wasm/dijkstra_llm.wasm`
- `wasm/dijkstra_gemini.js` + `wasm/dijkstra_gemini.wasm`
- `wasm/manifest.json` (build metadata + module path/export manifest)

Workflow outputs:

- Commits updated WASM files back into the branch (so the static UI can fetch them from `wasm/`)
- Uploads a `wasm-modules` artifact containing the same files for easier inspection/download
