Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Resolve-BinaryPath {
    param(
        [Parameter(Mandatory = $true)][string[]]$Candidates
    )
    $isWindows = ($env:OS -eq "Windows_NT")
    foreach ($candidate in $Candidates) {
        $raw = $candidate.Replace('/', '\')
        $exe = "$raw.exe"
        if ($isWindows -and (Test-Path -LiteralPath $exe -PathType Leaf)) {
            return (Resolve-Path $exe).Path
        }
        if (Test-Path -LiteralPath $raw -PathType Leaf) {
            return (Resolve-Path $raw).Path
        }
        if (Test-Path -LiteralPath $exe -PathType Leaf) {
            return (Resolve-Path $exe).Path
        }
    }
    return $null
}

function Test-IsPortableExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )
    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
        return ($bytes.Length -ge 2 -and $bytes[0] -eq 0x4D -and $bytes[1] -eq 0x5A) # "MZ"
    } catch {
        return $false
    }
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
    if (($env:OS -eq "Windows_NT") -and -not (Test-IsPortableExecutable -Path $resolved)) {
        throw "Resolved binary is not a Windows PE executable: $resolved"
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
    "--collect-all", "numpy",
    "--collect-all", "matplotlib",
    "--hidden-import", "matplotlib.backends.backend_tkagg",
    "--hidden-import", "matplotlib.backends.backend_agg",
    "desktop_runner/app.py"
)

$stagedFiles = Get-ChildItem -LiteralPath $stagingBin -File
foreach ($file in $stagedFiles) {
    $pyArgs += @("--add-binary", "$($file.FullName);binaries")
}

$exePath = Join-Path $repoRoot "dist/capstone-benchmark-runner.exe"
if (Test-Path -LiteralPath $exePath -PathType Leaf) {
    Remove-Item -LiteralPath $exePath -Force
}

python @pyArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "Expected executable missing: $exePath"
}
Write-Host "Built: $exePath"
