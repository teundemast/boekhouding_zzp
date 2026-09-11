# Start de boekhouding. Dubbelklikken kan ook: rechtermuisknop > Uitvoeren met PowerShell.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Eenmalige installatie..." -ForegroundColor Cyan
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
}

.\.venv\Scripts\python.exe -m tools.run @args
