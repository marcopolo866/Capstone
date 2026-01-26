# WebAssembly (Local Run)

This folder contains prebuilt WebAssembly modules used by the **Run Locally (WebAssembly)** option in `index.html`.

## Build / Update

Run the GitHub Actions workflow **Build WASM Modules** (`.github/workflows/build-wasm.yml`) to regenerate (it also runs automatically on pushes to `main`):

- `wasm/vf3_baseline.js` + `wasm/vf3_baseline.wasm`
- `wasm/vf3_gemini.js` + `wasm/vf3_gemini.wasm`
- `wasm/vf3_chatgpt.js` + `wasm/vf3_chatgpt.wasm`

These files are committed back into the repository so the static site can fetch them.
