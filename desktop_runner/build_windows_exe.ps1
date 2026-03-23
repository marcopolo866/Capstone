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

function Resolve-MingwRoot {
    $candidates = New-Object System.Collections.Generic.List[string]

    if ($env:MINGW_ROOT) {
        $candidates.Add($env:MINGW_ROOT)
    }

    $gpp = Get-Command g++ -ErrorAction SilentlyContinue
    if ($gpp -and $gpp.Source) {
        $binDir = Split-Path -Parent $gpp.Source
        $toolRoot = Split-Path -Parent $binDir
        if ($toolRoot) {
            $candidates.Add($toolRoot)
        }
    }

    $candidates.Add("C:\\msys64\\mingw64")
    $candidates.Add("C:\\mingw64")

    $seen = @{}
    foreach ($root in $candidates) {
        if (-not $root) {
            continue
        }
        if ($seen.ContainsKey($root)) {
            continue
        }
        $seen[$root] = $true
        $stdcpp = Join-Path $root "bin/libstdc++-6.dll"
        if (Test-Path -LiteralPath $stdcpp -PathType Leaf) {
            return $root
        }
    }

    throw "Unable to locate MinGW runtime root (missing libstdc++-6.dll). Checked: $($candidates -join ', ')"
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

        $genLines = @($genOut)
        if ($genLines.Count -lt 1) {
            throw "Generator produced no output for staged VF3 smoke test."
        }
        $lastLine = ($genLines | Select-Object -Last 1).ToString().Trim()
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
except OSError as exc:
    print(f"launch failed: {exc}", file=sys.stderr)
    sys.exit(126)

if proc.returncode != 0:
    print(
        f"vf3 returned code {proc.returncode} (0x{(proc.returncode & 0xFFFFFFFF):08X})",
        file=sys.stderr,
    )
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
    Write-Host ("Using binary {0}: {1}" -f $spec.Out, $resolved)
    Copy-Item -LiteralPath $resolved -Destination (Join-Path $stagingBin $spec.Out) -Force
}

$mingwRoot = Resolve-MingwRoot
Write-Host "Using MinGW runtime root: $mingwRoot"
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
Invoke-StagedVf3SmokeTest -RepoRoot $repoRoot -StagingBin $stagingBin

$pyArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "capstone-benchmark-runner",
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
