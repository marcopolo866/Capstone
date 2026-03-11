Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Resolve-BinaryPath {
    param(
        [Parameter(Mandatory = $true)][string[]]$Candidates
    )
    $isWindowsPlatform = ($env:OS -eq "Windows_NT")
    foreach ($candidate in $Candidates) {
        $raw = $candidate.Replace('/', '\')
        $exe = "$raw.exe"
        if ($isWindowsPlatform -and (Test-Path -LiteralPath $exe -PathType Leaf)) {
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

function Invoke-StagedVf3SmokeTest {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$StagingBin
    )
    $vf3Path = Join-Path $StagingBin "vf3.exe"
    if (-not (Test-Path -LiteralPath $vf3Path -PathType Leaf)) {
        throw "Staged VF3 baseline binary missing: $vf3Path"
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "python is required for staged VF3 smoke test during packaging."
    }
    $pythonExe = $pythonCommand.Source

    $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("vf3_pkg_smoke_" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmpDir | Out-Null
    try {
        Push-Location $RepoRoot
        try {
            $genOut = & $pythonExe "utilities/generate_graphs.py" --algorithm subgraph --n 5 --k 2 --density 0.01 --seed 424242 --out-dir $tmpDir
            if (-not $?) {
                throw "Generator failed for staged VF3 smoke test."
            }
        } finally {
            Pop-Location
        }

        if (-not $genOut -or $genOut.Count -lt 1) {
            throw "Generator produced no output for staged VF3 smoke test."
        }
        $lastLine = ($genOut | Select-Object -Last 1).ToString().Trim()
        $parts = $lastLine.Split(",")
        if ($parts.Count -lt 4) {
            throw "Failed to parse generated VF paths from output: $lastLine"
        }
        $vfPattern = $parts[2].Trim()
        $vfTarget = $parts[3].Trim()
        if (-not (Test-Path -LiteralPath $vfPattern -PathType Leaf)) {
            throw "Generated VF pattern missing for staged smoke test: $vfPattern"
        }
        if (-not (Test-Path -LiteralPath $vfTarget -PathType Leaf)) {
            throw "Generated VF target missing for staged smoke test: $vfTarget"
        }

        $runnerProbe = @'
import subprocess
import sys

binary, pattern, target = sys.argv[1:4]
try:
    proc = subprocess.run(
        [binary, "-u", "-r", "0", "-e", pattern, target],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
except subprocess.TimeoutExpired:
    print("timed out after 20 seconds", file=sys.stderr)
    sys.exit(124)

if proc.returncode != 0:
    details = (proc.stderr or proc.stdout or "").strip()
    if details:
        print(details[:4000], file=sys.stderr)
    # Map negative Windows-style process return codes into a non-zero Python exit.
    sys.exit(1)

sys.exit(0)
'@
        $probeOutput = $runnerProbe | & $pythonExe - $vf3Path $vfPattern $vfTarget 2>&1
        if ($LASTEXITCODE -ne 0) {
            $detail = ($probeOutput | Where-Object { $_ }) -join " | "
            throw "Staged VF3 smoke test failed for ${vf3Path}: $detail"
        }
        Write-Host "Staged VF3 smoke test passed: $vf3Path"
    } finally {
        if (Test-Path -LiteralPath $tmpDir) {
            Remove-Item -LiteralPath $tmpDir -Recurse -Force
        }
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
Invoke-StagedVf3SmokeTest -RepoRoot $repoRoot -StagingBin $stagingBin

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
