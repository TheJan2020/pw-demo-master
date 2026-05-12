@echo off
rem PW Demo Master — Windows batch runner (cmd.exe fallback for run.ps1).
setlocal

cd /d "%~dp0"

if not exist .venv (
    echo Creating virtualenv at .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create venv. Make sure Python 3.10+ is installed and on PATH.
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend\requirements.txt

if "%PORT%"=="" set PORT=8080
echo Starting PW Demo Master on http://localhost:%PORT%
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port %PORT% --reload
