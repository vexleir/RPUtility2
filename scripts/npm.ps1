$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$nodeDir = Join-Path $repoRoot ".tools\node"
$npmCmd = Join-Path $repoRoot ".tools\node\npm.cmd"

if (-not (Test-Path $npmCmd)) {
    throw "Portable npm was not found at '$npmCmd'."
}

$env:Path = "$nodeDir;$env:Path"
& $npmCmd @args
exit $LASTEXITCODE
