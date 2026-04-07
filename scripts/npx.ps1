$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$nodeDir = Join-Path $repoRoot ".tools\node"
$npxCmd = Join-Path $repoRoot ".tools\node\npx.cmd"

if (-not (Test-Path $npxCmd)) {
    throw "Portable npx was not found at '$npxCmd'."
}

$env:Path = "$nodeDir;$env:Path"
& $npxCmd @args
exit $LASTEXITCODE
