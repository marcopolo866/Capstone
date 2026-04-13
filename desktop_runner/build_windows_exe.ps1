# - This script is the Windows packaging entrypoint for the desktop runner and
#   should stay aligned with build_runner.py and the Unix bundling flow.
# - Keep binary discovery conservative because packaging fails late when the
#   staged solver set and copied runtime DLLs come from different toolchains.

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
    $msysRoot = "C:\\msys64\\mingw64"
    $msysBin = Join-Path $msysRoot "bin"
    $pathParts = @($env:PATH -split ';' | Where-Object { $_ })

    $preferMsys = $false
    foreach ($part in $pathParts) {
        if ($part.TrimEnd('\').ToLowerInvariant() -eq $msysBin.ToLowerInvariant()) {
            $preferMsys = $true
            break
        }
    }

    if ((Test-Path -LiteralPath (Join-Path $msysBin "g++.exe") -PathType Leaf) -and ($preferMsys -or $env:GITHUB_ACTIONS -eq "true")) {
        $candidates.Add($msysRoot)
    }

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

    $candidates.Add($msysRoot)
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
    $vf3Path = Join-Path $StagingBin "vf3_baseline.exe"
    if (-not (Test-Path -LiteralPath $vf3Path -PathType Leaf)) {
        $vf3Path = Join-Path $StagingBin "vf3.exe"
    }
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

function Publish-BuiltExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

    $targetDir = Split-Path -Parent $TargetPath
    if (-not (Test-Path -LiteralPath $targetDir)) {
        New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    }

    $targetAvailable = $true
    if (Test-Path -LiteralPath $TargetPath -PathType Leaf) {
        try {
            Remove-Item -LiteralPath $TargetPath -Force
        } catch {
            $targetAvailable = $false
        }
    }

    if ($targetAvailable) {
        Copy-Item -LiteralPath $SourcePath -Destination $TargetPath -Force
        return $TargetPath
    }

    $targetBaseName = [System.IO.Path]::GetFileNameWithoutExtension($TargetPath)
    $targetExtension = [System.IO.Path]::GetExtension($TargetPath)
    $fallbackLeaf = $targetBaseName + ".new" + $targetExtension
    $fallbackPath = Join-Path $targetDir $fallbackLeaf
    if (Test-Path -LiteralPath $fallbackPath -PathType Leaf) {
        try {
            Remove-Item -LiteralPath $fallbackPath -Force
        } catch {
        }
    }
    Copy-Item -LiteralPath $SourcePath -Destination $fallbackPath -Force
    $warningMessage =
        "Could not replace '$TargetPath' because it is locked or not writable. " +
        "A fresh build was written to '$fallbackPath'. Close the running app and replace the original file when convenient."
    Write-Warning $warningMessage
    return $fallbackPath
}

$discoveryRaw = & python "scripts/solver_discovery.py"
if (-not $?) {
    throw "Failed to discover solver variants from scripts/solver_discovery.py"
}
$discoveryJson = ($discoveryRaw -join "`n")
try {
    $convertFromJson = Get-Command ConvertFrom-Json -ErrorAction Stop
    if ($convertFromJson.Parameters.ContainsKey("Depth")) {
        $discovery = $discoveryJson | ConvertFrom-Json -Depth 16
    } else {
        # Windows PowerShell 5.1 does not support ConvertFrom-Json -Depth.
        $discovery = $discoveryJson | ConvertFrom-Json
    }
} catch {
    throw "Failed to parse solver discovery JSON: $($_.Exception.Message)"
}

$binarySpec = @()
foreach ($row in @($discovery.solvers)) {
    if (-not $row) { continue }
    $variantId = [string]$row.variant_id
    $binaryPath = [string]$row.binary_path
    if (-not $variantId -or -not $binaryPath) { continue }
    $candidates = @($binaryPath)
    if ($variantId -eq "glasgow_baseline") {
        $candidates += @(
            "baselines/glasgow-subgraph-solver/build/Release/glasgow_subgraph_solver",
            "baselines/glasgow-subgraph-solver/build/src/glasgow_subgraph_solver",
            "baselines/glasgow-subgraph-solver/build/src/Release/glasgow_subgraph_solver"
        )
    } elseif ($variantId -eq "dijkstra_chatgpt") {
        $candidates += @("src/dijkstra_llm")
    } elseif ($variantId -eq "vf3_chatgpt") {
        $candidates += @("src/chatvf3")
    } elseif ($variantId -eq "vf3_gemini") {
        $candidates += @("src/vf3")
    }
    $binarySpec += @{
        Out = "$variantId.exe"
        VariantId = $variantId
        Candidates = $candidates
        Family = [string]$row.family
        Algorithm = [string]$row.algorithm
        Role = [string]$row.role
        Label = [string]$row.label
        LlmKey = if ($null -ne $row.llm_key) { [string]$row.llm_key } else { $null }
        LlmLabel = if ($null -ne $row.llm_label) { [string]$row.llm_label } else { $null }
    }
}

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

$solverManifest = @{
    schema_version = 1
    solvers = @()
}
foreach ($spec in $binarySpec) {
    $solverManifest.solvers += @{
        variant_id = $spec.VariantId
        family = $spec.Family
        algorithm = $spec.Algorithm
        role = $spec.Role
        label = $spec.Label
        llm_key = $spec.LlmKey
        llm_label = $spec.LlmLabel
        binary_name = $spec.VariantId
    }
}
$manifestPath = Join-Path $stagingBin "solver_variants.json"
$solverManifest | ConvertTo-Json -Depth 16 | Out-File -FilePath $manifestPath -Encoding utf8

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
    "--hidden-import", "tkwebview2.tkwebview2",
    "--hidden-import", "clr",
    "--hidden-import", "webview.window",
    "--hidden-import", "webview.platforms.edgechromium",
    "desktop_runner/app.py"
)

$pyiTempRoot = Join-Path $repoRoot "desktop_runner/.pyinstaller-tmp"
$pyiDistDir = Join-Path $pyiTempRoot "dist"
$pyiWorkDir = Join-Path $pyiTempRoot "build"
$pyiSpecDir = Join-Path $pyiTempRoot "spec"
if (Test-Path -LiteralPath $pyiTempRoot) {
    Remove-Item -LiteralPath $pyiTempRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $pyiDistDir | Out-Null
New-Item -ItemType Directory -Force -Path $pyiWorkDir | Out-Null
New-Item -ItemType Directory -Force -Path $pyiSpecDir | Out-Null
$pyArgs += @("--distpath", $pyiDistDir, "--workpath", $pyiWorkDir, "--specpath", $pyiSpecDir)

$stagedFiles = Get-ChildItem -LiteralPath $stagingBin -File
foreach ($file in $stagedFiles) {
    $pyArgs += @("--add-binary", "$($file.FullName);binaries")
}

$visualizerJs = Join-Path $repoRoot "js/app/07-visualization-api-bootstrap.js"
if (-not (Test-Path -LiteralPath $visualizerJs -PathType Leaf)) {
    throw "Missing visualizer bootstrap script: $visualizerJs"
}
$pyArgs += @("--add-data", "$visualizerJs;js/app")

$exePath = Join-Path $repoRoot "dist/capstone-benchmark-runner.exe"
$builtExePath = Join-Path $pyiDistDir "capstone-benchmark-runner.exe"

python @pyArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $builtExePath -PathType Leaf)) {
    throw "Expected executable missing from PyInstaller dist path: $builtExePath"
}
$publishedExePath = Publish-BuiltExecutable -SourcePath $builtExePath -TargetPath $exePath
Write-Host "Built: $publishedExePath"
