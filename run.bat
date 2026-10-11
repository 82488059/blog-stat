@echo off
REM Blog stats API — bind 127.0.0.1 ONLY. Do NOT use 0.0.0.0.
REM Expose publicly via nginx reverse proxy to /api/, never open port 3001.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
set STAT_DATA_DIR=%~dp0data
REM Optional: set STAT_PAGES_TOKEN=... to enable GET /api/stat/pages
REM Optional: set STAT_CORS_ORIGINS=https://www.xssl.online,https://82488059.github.io
REM Optional: set STAT_RATE_LIMIT_MAX=120
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 3001
