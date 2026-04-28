# Android Benchmark Runner

This module is a native Android version of the desktop benchmark runner.

It is intentionally top-level and self-contained so the existing desktop,
headless, web, and CI entrypoints do not need to change.

## Scope

Implemented in this module:

- Native Android app shell (`app/src/main/java/.../MainActivity.java`)
- On-device benchmark execution through an NDK library
- Solver catalog matching the current desktop-discovered solver IDs
- Generated independent-variable runs for shortest-path and subgraph tabs
- Variant selection, baseline injection, pause, resume, abort, run log, progress
- Manifest import/export using the same manifest schema marker
- Session exports:
  - `benchmark-session.json`
  - `benchmark-session.csv`
  - `benchmark-datapoints.ndjson`
  - `benchmark-trials.ndjson`
  - `benchmark-manifest.json`
- Runtime and memory chart views
- Runtime summary/statistics view
- Mobile graph visualizer for generated target graphs
- Dataset catalog UI matching the desktop dataset list
- Raw dataset downloads into app-specific external storage

Current native execution core:

- `dijkstra` and `sp_via` read the generated CSV input and run native Dijkstra.
- `vf3` and `glasgow` read generated `.vf`/vertex-labelled `.lad` inputs and
  run a native non-induced, label-exact subgraph counting fallback.
- The Java bridge is structured so per-variant Android solver libraries can be
  swapped in behind `NativeSolverBridge` without changing UI or export schema.

Dataset archive converters and direct compilation of every LLM C++ variant into
separate Android-native solver libraries are the remaining parity work before
dataset-mode and per-variant performance comparisons should be treated as
publication-grade.

## Required Android Toolchain

The module is pinned for:

- JDK 17
- Android Gradle Plugin 9.2.0
- Gradle 9.4.1
- compile SDK 36
- Android SDK Build Tools 36.0.0
- Android NDK 28.2.13676358

Android Studio is the easiest way to install those pieces. From Android Studio:

1. Open `android_runner/`.
2. Let Gradle sync.
3. Install the requested SDK/NDK components when prompted.
4. Run the `app` configuration on a device or emulator.

Command-line build after the toolchain is installed:

```powershell
cd android_runner
gradle :app:assembleDebug
```

If you generate a Gradle wrapper locally, keep the wrapper version aligned with
Gradle 9.4.1:

```powershell
cd android_runner
gradle wrapper --gradle-version 9.4.1
.\gradlew.bat :app:assembleDebug
```

## Website Download

The existing `.github/workflows/build-benchmark-runner.yml` workflow now builds
the Android APK in the same workflow as the desktop runners. Successful `main`
builds publish `benchmark-runner-android.apk` to the public
`benchmark-runner-latest` release, and the website detects Android browsers
before the generic Linux check so Android users receive the APK instead of the
Linux desktop bundle.

The workflow artifact fallback is named `benchmark-runner-android`; GitHub
serves workflow artifacts as zip files, so fallback downloads contain the APK
inside the zip.

## Java Source Layout

Small data/model classes are consolidated under:

- `model/BenchmarkModels.java`

Larger behavior remains split by responsibility:

- `MainActivity.java`: Android UI shell
- `engine/`: generation, native execution bridge, benchmark orchestration
- `data/`: catalogs, manifest/session export, dataset download helpers
- `ui/`: custom chart and visualizer views

## Desktop Dependency Note

The desktop/headless Python path still needs its Python dependencies when you
run desktop parity checks:

```powershell
python -m pip install -r desktop_runner/requirements.txt
```

For just the import error seen during inspection:

```powershell
python -m pip install psutil==6.1.1
```
