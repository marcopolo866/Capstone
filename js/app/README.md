# Frontend Runtime Chunks

These files are an ordered split of the original monolithic frontend runtime script (the old top-level `app.js` file has been removed).

## Load Order (required)

`index.html` loads these sequentially:

1. `01-state-progress-checks.js`
2. `02-inputs-generator-ui.js`
3. `03-generator-estimation.js`
4. `04-local-wasm-and-local-runner.js`
5. `05-github-workflow-runner.js`
6. `06-results-and-charts.js`
7. `07-visualization-api-bootstrap.js`

## Design Note

This is a behavior-preserving split, not a full ES module migration. Files share globals intentionally.

## Validation

Use:

```powershell
& 'C:\Program Files\nodejs\node.exe' --check js/app/01-state-progress-checks.js
```

Repeat the Node syntax check for each chunk.
