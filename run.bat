@echo off
REM One-command start (Windows): double-click run.bat or run it in a terminal, then open http://localhost:8000
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
echo Installing packages (first run takes ~1 minute)...
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
if not exist .env if not exist ..\.env echo WARNING: no .env found here or one folder up. Copy .env.example to .env and add PORTKEY_API_KEY.
echo.
echo Career Scout is starting at http://localhost:8000  (Ctrl+C to stop)
.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
