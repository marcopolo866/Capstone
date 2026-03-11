param(
    [string]$CMakeGenerator = "MinGW Makefiles"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:IsWindowsHost = ([System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT)

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

function Ensure-Msys2ToolchainPath {
    if (-not $script:IsWindowsHost) {
        return
    }
    $msysMingwBin = "C:\msys64\mingw64\bin"
    $msysUsrBin = "C:\msys64\usr\bin"
    if (-not (Test-Path -LiteralPath (Join-Path $msysMingwBin "g++.exe") -PathType Leaf)) {
        return
    }
    $currentGppCmd = Get-Command g++ -ErrorAction SilentlyContinue
    $currentGpp = if ($currentGppCmd) { $currentGppCmd.Source } else { "" }
    if ($currentGpp -and $currentGpp.StartsWith($msysMingwBin, [System.StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    Write-Host "Preferring MSYS2 MinGW toolchain from $msysMingwBin"
    $env:PATH = "$msysMingwBin;$msysUsrBin;$env:PATH"
}

function Assert-GmpAvailable {
    if (-not $script:IsWindowsHost) {
        return
    }
    $msysBash = "C:\msys64\usr\bin\bash.exe"
    $msysGpp = "C:\msys64\mingw64\bin\g++.exe"
    $gpp = Get-Command g++ -ErrorAction SilentlyContinue
    if (-not $gpp) {
        throw "Missing required command: g++"
    }
    $binDir = Split-Path -Parent $gpp.Source
    $toolRoot = Split-Path -Parent $binDir
    $libDir = Join-Path $toolRoot "lib"

    $hasGmp = (Test-Path -LiteralPath (Join-Path $libDir "libgmp.dll.a") -PathType Leaf) -or
        (Test-Path -LiteralPath (Join-Path $libDir "libgmp.a") -PathType Leaf)
    $hasGmpxx = (Test-Path -LiteralPath (Join-Path $libDir "libgmpxx.dll.a") -PathType Leaf) -or
        (Test-Path -LiteralPath (Join-Path $libDir "libgmpxx.a") -PathType Leaf)

    if ($hasGmp -and $hasGmpxx) {
        return
    }

    $extraHint = @"
If using MSYS2, install with:
  C:\msys64\usr\bin\bash.exe -lc "pacman -S --needed mingw-w64-x86_64-gcc mingw-w64-x86_64-cmake mingw-w64-x86_64-make mingw-w64-x86_64-gmp"
"@
    if ((Test-Path -LiteralPath $msysBash -PathType Leaf) -and -not (Test-Path -LiteralPath $msysGpp -PathType Leaf)) {
        $extraHint = @"
MSYS2 is present but the MinGW64 toolchain is missing.
Install it with:
  C:\msys64\usr\bin\bash.exe -lc "pacman -S --needed mingw-w64-x86_64-gcc mingw-w64-x86_64-cmake mingw-w64-x86_64-make mingw-w64-x86_64-gmp"
"@
    }

    throw @"
Missing GMP/GMPXX development libraries for the active compiler:
  g++: $($gpp.Source)
  expected under: $libDir

$extraHint
"@
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    Write-Host ""
    Write-Host "==> $Label"
    $script:LASTEXITCODE = 0
    & $Action
    if (-not $?) {
        throw "Step failed: $Label"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Label (exit code $LASTEXITCODE)"
    }
}

function Test-ExpectedOutput {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-Path $Path -PathType Leaf) {
        return $true
    }
    if ($script:IsWindowsHost) {
        if (Test-Path ($Path + '.exe') -PathType Leaf) {
            return $true
        }
    }
    return $false
}

function Resolve-BinaryPathForWindowsPackaging {
    param([Parameter(Mandatory = $true)][string]$BasePath)
    $raw = $BasePath.Replace('/', '\')
    $exe = "$raw.exe"
    if ($script:IsWindowsHost -and (Test-Path -LiteralPath $exe -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $exe).Path
    }
    if (Test-Path -LiteralPath $raw -PathType Leaf) {
        return (Resolve-Path -LiteralPath $raw).Path
    }
    if (Test-Path -LiteralPath $exe -PathType Leaf) {
        return (Resolve-Path -LiteralPath $exe).Path
    }
    return $null
}

function Reset-CMakeBuildDirIfNeeded {
    param(
        [Parameter(Mandatory = $true)][string]$BuildDir,
        [Parameter(Mandatory = $true)][string]$ExpectedGenerator
    )
    $cachePath = Join-Path $BuildDir "CMakeCache.txt"
    if (-not (Test-Path $cachePath -PathType Leaf)) {
        return
    }
    try {
        $cacheText = Get-Content -Raw -LiteralPath $cachePath
    } catch {
        return
    }
    $genMatch = [regex]::Match($cacheText, '(?m)^CMAKE_GENERATOR:INTERNAL=(.+)$')
    $cachedGenerator = if ($genMatch.Success) { $genMatch.Groups[1].Value.Trim() } else { "" }
    if ($cachedGenerator -and $cachedGenerator -ne $ExpectedGenerator) {
        Write-Host "Cleaning stale Glasgow CMake build directory (generator mismatch: '$cachedGenerator' vs '$ExpectedGenerator')"
        Remove-Item -Recurse -Force $BuildDir
        return
    }
}

Ensure-Msys2ToolchainPath

Require-Command git
Require-Command g++
Require-Command make
Require-Command cmake
Assert-GmpAvailable
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCommand) {
    $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $PythonCommand) {
    throw "Missing required command: python (or py)"
}
$PythonExe = $PythonCommand.Source

Invoke-Step "Updating submodules" { git submodule update --init --recursive }

Invoke-Step "Building Dijkstra baseline" {
    g++ -std=c++17 -O3 -I "baselines/nyaan-library" "baselines/dijkstra_main.cpp" -o "baselines/dijkstra"
}
Invoke-Step "Building Dijkstra ChatGPT" {
    g++ -std=c++17 -O3 "src/[CHATGPT] Shortest Path.cpp" -o "src/dijkstra_llm"
}
Invoke-Step "Building Dijkstra Gemini" {
    g++ -std=c++17 -O3 "src/[GEMINI] Shortest Path.cpp" -o "src/dijkstra_gemini"
}

# Keep VF3 baseline on safer optimization flags; -O3 has produced unstable binaries
# on some toolchains (observed as access violations on small generated cases).
$vf3CFlags = "-std=c++11 -O2 -DNDEBUG -Wno-deprecated -fno-strict-aliasing -fwrapv"
if ($script:IsWindowsHost) {
    # vf3lib uses WIN32 guards for signal/time headers; MinGW also needs getopt declarations explicitly.
    $vf3CFlags += " -DWIN32 -include getopt.h"
}
Invoke-Step "Cleaning VF3 baseline outputs (fresh rebuild)" {
    foreach ($candidate in @("baselines/vf3lib/bin/vf3", "baselines/vf3lib/bin/vf3.exe")) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            Remove-Item -LiteralPath $candidate -Force
        }
    }
}
Invoke-Step "Building VF3 baseline (vf3lib)" {
    make -C baselines/vf3lib vf3 "CFLAGS=$vf3CFlags"
}
Invoke-Step "VF3 baseline smoke test (small generated subgraph case)" {
    $vf3Binary = Resolve-BinaryPathForWindowsPackaging -BasePath "baselines/vf3lib/bin/vf3"
    if (-not $vf3Binary -or -not (Test-Path -LiteralPath $vf3Binary -PathType Leaf)) {
        throw "Missing VF3 baseline binary for smoke test: $vf3Binary"
    }
    Write-Host "VF3 smoke test binary: $vf3Binary"

    $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("vf3_smoke_" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmpDir | Out-Null
    try {
        $genOut = & $PythonExe "utilities/generate_graphs.py" --algorithm subgraph --n 5 --k 2 --density 0.01 --seed 424242 --out-dir $tmpDir
        if (-not $?) {
            throw "Generator failed for VF3 smoke test."
        }
        $genLines = @($genOut)
        if ($genLines.Count -lt 1) {
            throw "Generator produced no output for VF3 smoke test."
        }
        $lastLine = ($genLines | Select-Object -Last 1).ToString().Trim()
        $parts = $lastLine.Split(",")
        if ($parts.Count -lt 4) {
            throw "Failed to parse generated VF paths from output: $lastLine"
        }
        $vfPattern = $parts[2].Trim()
        $vfTarget = $parts[3].Trim()
        if (-not (Test-Path -LiteralPath $vfPattern -PathType Leaf)) {
            throw "Generated VF pattern missing: $vfPattern"
        }
        if (-not (Test-Path -LiteralPath $vfTarget -PathType Leaf)) {
            throw "Generated VF target missing: $vfTarget"
        }
        & $vf3Binary -u -r 0 -e $vfPattern $vfTarget | Out-Null
        if (-not $?) {
            throw "VF3 baseline smoke test command failed."
        }
    } finally {
        if (Test-Path -LiteralPath $tmpDir) {
            Remove-Item -LiteralPath $tmpDir -Recurse -Force
        }
    }
}
Invoke-Step "Building VF3 Gemini" {
    g++ -std=c++17 -O3 "src/[GEMINI] Subgraph Isomorphism.cpp" -o "src/vf3"
}
Invoke-Step "Building VF3 ChatGPT" {
    g++ -std=c++17 -O3 "src/[CHATGPT] Subgraph Isomorphism.cpp" -o "src/chatvf3"
}

Invoke-Step "Building Glasgow ChatGPT" {
    g++ -std=c++17 -O3 "src/[CHATGPT] Glasgow.cpp" -o "src/glasgow_chatgpt"
}
Invoke-Step "Building Glasgow Gemini" {
    g++ -std=c++17 -O3 "src/[GEMINI] Glasgow.cpp" -o "src/glasgow_gemini"
}
Invoke-Step "Patching Glasgow submodule for MinGW loooong/size_t ambiguity" {
    @'
from pathlib import Path

path = Path("baselines/glasgow-subgraph-solver/gss/sip_decomposer.cc")
text = path.read_text(encoding="utf-8")
updated = text
updated = updated.replace(
    "n_choose_k<loooong>(unmapped_target_vertices, isolated_pattern_vertices.size());",
    "n_choose_k<loooong>(unmapped_target_vertices, static_cast<unsigned long>(isolated_pattern_vertices.size()));",
)
updated = updated.replace(
    "factorial<loooong>(isolated_pattern_vertices.size());",
    "factorial<loooong>(static_cast<unsigned long>(isolated_pattern_vertices.size()));",
)
if updated != text:
    path.write_text(updated, encoding="utf-8")
    print(f"Patched {path}")
else:
    print(f"No patch changes needed for {path}")
'@ | & $PythonExe -
}

$cmakeArgs = @(
    "-S", "baselines/glasgow-subgraph-solver",
    "-B", "baselines/glasgow-subgraph-solver/build",
    "-DCMAKE_BUILD_TYPE=Release",
    "-DCMAKE_CXX_FLAGS=-O3"
)

if ($CMakeGenerator) {
    $cmakeArgs += @("-G", $CMakeGenerator)
}

Reset-CMakeBuildDirIfNeeded -BuildDir "baselines/glasgow-subgraph-solver/build" -ExpectedGenerator $CMakeGenerator

Invoke-Step "Configuring Glasgow baseline" {
    & cmake @cmakeArgs
}
Invoke-Step "Building Glasgow baseline" {
    cmake --build "baselines/glasgow-subgraph-solver/build" --config Release --parallel
}
Invoke-Step "Checking Glasgow parity" {
    & $PythonExe "scripts/check-glasgow-parity.py"
}

$expectedOutputs = @(
    "baselines/dijkstra",
    "src/dijkstra_llm",
    "src/dijkstra_gemini",
    "src/vf3",
    "src/chatvf3",
    "src/glasgow_chatgpt",
    "src/glasgow_gemini",
    "baselines/vf3lib/bin/vf3",
    "baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver"
)

$missing = @()
foreach ($path in $expectedOutputs) {
    if (-not (Test-ExpectedOutput $path)) {
        $missing += $path
    }
}

if ($missing.Count -gt 0) {
    throw ("Build completed with missing outputs:`n" + ($missing -join "`n"))
}

Write-Host ""
Write-Host "Local build complete."
