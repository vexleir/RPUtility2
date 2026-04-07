$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$npmScript = Join-Path $repoRoot "scripts\npm.ps1"

if (-not (Test-Path $npmScript)) {
    throw "Portable npm helper was not found at '$npmScript'."
}

& $npmScript run check:frontend
exit $LASTEXITCODE
