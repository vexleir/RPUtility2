$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    & (Join-Path $repoRoot "scripts\check-frontend.ps1")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    pytest tests\test_rpg_foundation.py tests\test_rules_resolution.py tests\test_sheet_state.py -q -p no:cacheprovider
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
