param([switch]$Demo)
$ErrorActionPreference = "Stop"
$project = Split-Path $PSScriptRoot -Parent
$pythonExe = Join-Path $project ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $pythonExe)) { throw "Create .venv and install the backend dependencies as described in README.md." }
Push-Location (Join-Path $project "backend")
try {
    if ($Demo) { & $pythonExe -m app.cli serve --demo }
    else { & $pythonExe -m app.cli serve }
    exit $LASTEXITCODE
} finally { Pop-Location }
