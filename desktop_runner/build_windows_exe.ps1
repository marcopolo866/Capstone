Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Require-File {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing required file: $Path"
    }
}

$binaryFiles = @(
    "baselines/dijkstra.exe",
    "src/dijkstra_llm.exe",
    "src/dijkstra_gemini.exe",
    "baselines/vf3lib/bin/vf3.exe",
    "src/chatvf3.exe",
    "src/vf3.exe",
    "baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver.exe",
    "src/glasgow_chatgpt.exe",
    "src/glasgow_gemini.exe"
)

foreach ($path in $binaryFiles) { Require-File -Path $path }

$pyArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "capstone-benchmark-runner",
    "--collect-data", "matplotlib",
    "--hidden-import", "matplotlib.backends.backend_tkagg",
    "--hidden-import", "matplotlib.backends.backend_agg",
    "--add-binary", "baselines/dijkstra.exe;binaries",
    "--add-binary", "src/dijkstra_llm.exe;binaries",
    "--add-binary", "src/dijkstra_gemini.exe;binaries",
    "--add-binary", "baselines/vf3lib/bin/vf3.exe;binaries",
    "--add-binary", "src/chatvf3.exe;binaries",
    "--add-binary", "src/vf3.exe;binaries",
    "--add-binary", "baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver.exe;binaries",
    "--add-binary", "src/glasgow_chatgpt.exe;binaries",
    "--add-binary", "src/glasgow_gemini.exe;binaries",
    "desktop_runner/app.py"
)

$mingwRoot = $env:MINGW_ROOT
if (-not $mingwRoot -or -not (Test-Path -LiteralPath $mingwRoot)) {
    $mingwRoot = "C:\\msys64\\mingw64"
}
$dllCandidates = @(
    "libstdc++-6.dll",
    "libgcc_s_seh-1.dll",
    "libwinpthread-1.dll",
    "libgmp-10.dll",
    "libzstd.dll",
    "zlib1.dll"
)
foreach ($dll in $dllCandidates) {
    $dllPath = Join-Path $mingwRoot "bin/$dll"
    if (Test-Path -LiteralPath $dllPath -PathType Leaf) {
        $pyArgs += @("--add-binary", "$dllPath;binaries")
    }
}

python @pyArgs

$exePath = Join-Path $repoRoot "dist/capstone-benchmark-runner.exe"
Require-File -Path $exePath
Write-Host "Built: $exePath"
