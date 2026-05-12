# PW Demo Master — Windows PowerShell runner.
# Mirrors run.sh: creates a venv on first run, installs deps, starts uvicorn.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtualenv at .venv..."
    python -m venv .venv
}

# Activate the venv for the duration of this script.
& .\.venv\Scripts\Activate.ps1

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend/requirements.txt

$port = if ($env:PORT) { $env:PORT } else { "8080" }
Write-Host "Starting PW Demo Master on http://localhost:$port"
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $port --reload
