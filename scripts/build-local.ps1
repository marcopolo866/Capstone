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

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $pythonCmd) {
    throw "Missing required command: python (or py)"
}

$args = @("scripts/build-local.py", "--backend", "sh")
if ($CMakeGenerator -and $CMakeGenerator.Trim()) {
    $args += @("--cmake-generator", $CMakeGenerator.Trim())
}
if ($env:BUILD_LOCAL_FAST) {
    $args += "--fast"
}
if ($Passthrough -and $Passthrough.Count -gt 0) {
    $args += "--"
    $args += $Passthrough
}

& $pythonCmd.Source @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
