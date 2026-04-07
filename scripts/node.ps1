$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$nodeExe = Join-Path $repoRoot ".tools\node\node.exe"

if (-not (Test-Path $nodeExe)) {
    throw "Portable Node was not found at '$nodeExe'."
}

& $nodeExe @args
exit $LASTEXITCODE
