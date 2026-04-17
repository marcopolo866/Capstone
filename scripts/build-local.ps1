# - This PowerShell wrapper mirrors scripts/build-local.sh but preserves Windows
#   ergonomics such as parameter binding and generator defaults.
# - Keep argument forwarding transparent so troubleshooting can focus on the
#   shared Python build logic instead of wrapper-specific behavior.

param(
    [string]$CMakeGenerator = "MinGW Makefiles",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Passthrough
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pythonSource = $null
if ($env:CAPSTONE_PYTHON_EXE -and (Test-Path -LiteralPath $env:CAPSTONE_PYTHON_EXE -PathType Leaf)) {
    $pythonSource = $env:CAPSTONE_PYTHON_EXE
} else {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        $pythonCmd = Get-Command py -ErrorAction SilentlyContinue
    }
    if ($pythonCmd) {
        $pythonSource = $pythonCmd.Source
    }
}
if (-not $pythonSource) {
    throw "Missing required command: python (or py)"
}

$args = @("scripts/build-local-core.py")
if ($CMakeGenerator -and $CMakeGenerator.Trim()) {
    $args += @("--cmake-generator", $CMakeGenerator.Trim())
}
if ($env:BUILD_LOCAL_VALIDATION) {
    $args += @("--validation", $env:BUILD_LOCAL_VALIDATION)
}
if ($env:BUILD_LOCAL_FAST) {
    $args += "--fast"
}
if ($env:BUILD_LOCAL_SANITIZER) {
    $args += @("--sanitizer", $env:BUILD_LOCAL_SANITIZER)
}
if ($env:BUILD_LOCAL_SUPPRESS_DIAGNOSTICS) {
    $args += "--suppress-diagnostics"
}
if ($Passthrough -and $Passthrough.Count -gt 0) {
    $args += "--"
    $args += $Passthrough
}

& $pythonSource @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
