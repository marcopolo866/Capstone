# Local Compilation Command

Run from the repository root. These scripts compile the binaries used by the current native benchmarking / GitHub artifact pipeline outputs.

## Prerequisites

- `git`
- `g++`
- `make`
- `cmake`
- Submodules available (the scripts run `git submodule update --init --recursive`)

Notes:
- Windows builds are expected to use a MinGW/MSYS2 toolchain by default (`MinGW Makefiles`).
- If you use a different CMake generator, pass it to the PowerShell script or set `CMAKE_GENERATOR` for the Bash script.

## Windows (PowerShell, MinGW/MSYS2 toolchain in PATH)

```powershell
.\scripts\build-local.ps1
```

Optional generator override:

```powershell
.\scripts\build-local.ps1 -CMakeGenerator "Ninja"
```

## macOS / Linux (Bash)

```bash
bash scripts/build-local.sh
```

Optional generator override:

```bash
CMAKE_GENERATOR="Ninja" bash scripts/build-local.sh
```
