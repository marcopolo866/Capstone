param(
    [string]$CMakeGenerator = "MinGW Makefiles"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
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
    if ($IsWindows -or $env:OS -eq 'Windows_NT') {
        if (Test-Path ($Path + '.exe') -PathType Leaf) {
            return $true
        }
    }
    return $false
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

Require-Command git
Require-Command g++
Require-Command make
Require-Command cmake

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

Invoke-Step "Building VF3 baseline (vf3lib)" {
    make -C baselines/vf3lib vf3 'CFLAGS=-std=c++11 -O3 -DNDEBUG -Wno-deprecated'
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
