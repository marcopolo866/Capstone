Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Resolve-BinaryPath {
    param(
        [Parameter(Mandatory = $true)][string[]]$Candidates
    )
    foreach ($candidate in $Candidates) {
        $raw = $candidate.Replace('/', '\')
        if (Test-Path -LiteralPath $raw -PathType Leaf) {
            return (Resolve-Path $raw).Path
        }
        $exe = "$raw.exe"
        if (Test-Path -LiteralPath $exe -PathType Leaf) {
            return (Resolve-Path $exe).Path
        }
    }
    return $null
}

$binarySpec = @(
    @{ Out = "dijkstra.exe"; Candidates = @("baselines/dijkstra") },
    @{ Out = "dijkstra_llm.exe"; Candidates = @("src/dijkstra_llm") },
    @{ Out = "dijkstra_gemini.exe"; Candidates = @("src/dijkstra_gemini") },
    @{ Out = "vf3.exe"; Candidates = @("baselines/vf3lib/bin/vf3") },
    @{ Out = "chatvf3.exe"; Candidates = @("src/chatvf3") },
    @{ Out = "vf3_gemini.exe"; Candidates = @("src/vf3") },
    @{ Out = "glasgow_subgraph_solver.exe"; Candidates = @(
        "baselines/glasgow-subgraph-solver/build/glasgow_subgraph_solver",
        "baselines/glasgow-subgraph-solver/build/Release/glasgow_subgraph_solver",
        "baselines/glasgow-subgraph-solver/build/src/glasgow_subgraph_solver",
        "baselines/glasgow-subgraph-solver/build/src/Release/glasgow_subgraph_solver"
    ) },
    @{ Out = "glasgow_chatgpt.exe"; Candidates = @("src/glasgow_chatgpt") },
    @{ Out = "glasgow_gemini.exe"; Candidates = @("src/glasgow_gemini") }
)

$stagingRoot = Join-Path $repoRoot "desktop_runner/.staging"
$stagingBin = Join-Path $stagingRoot "binaries"
if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stagingBin | Out-Null

foreach ($spec in $binarySpec) {
    $resolved = Resolve-BinaryPath -Candidates $spec.Candidates
    if (-not $resolved) {
        throw "Missing required binary. Tried: $($spec.Candidates -join ', ')"
    }
    Copy-Item -LiteralPath $resolved -Destination (Join-Path $stagingBin $spec.Out) -Force
}

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
        Copy-Item -LiteralPath $dllPath -Destination (Join-Path $stagingBin $dll) -Force
    }
}

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
    "desktop_runner/app.py"
)

$stagedFiles = Get-ChildItem -LiteralPath $stagingBin -File
foreach ($file in $stagedFiles) {
    $pyArgs += @("--add-binary", "$($file.FullName);binaries")
}

python @pyArgs

$exePath = Join-Path $repoRoot "dist/capstone-benchmark-runner.exe"
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "Expected executable missing: $exePath"
}
Write-Host "Built: $exePath"
