@echo off
setlocal
set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found in %APP_DIR%.
  echo Please run setup first:
  echo   python -m venv .venv
  echo   .\.venv\Scripts\Activate.ps1
  echo   pip install -r requirements.txt
  pause
  exit /b 1
)

start "Downloader Server" "%APP_DIR%\.venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000

timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8000
