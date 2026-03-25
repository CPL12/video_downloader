@echo off
setlocal
set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"
set "PORT=8000"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found in %APP_DIR%.
  echo Please run setup first:
  echo   python -m venv .venv
  echo   .\.venv\Scripts\Activate.ps1
  echo   pip install -r requirements.txt
  pause
  exit /b 1
)

for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)"`) do (
  if not "%%P"=="" (
    echo Stopping existing server on port %PORT% (PID %%P^)...
    taskkill /PID %%P /T /F >nul 2>&1
  )
)

start "Downloader Server" "%APP_DIR%\.venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port %PORT%

powershell -NoProfile -Command ^
  "$deadline = (Get-Date).AddSeconds(15);" ^
  "do {" ^
  "  Start-Sleep -Milliseconds 500;" ^
  "  try {" ^
  "    $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/' -UseBasicParsing -TimeoutSec 2;" ^
  "    if ($resp.StatusCode -eq 200) { exit 0 }" ^
  "  } catch {}" ^
  "} while ((Get-Date) -lt $deadline);" ^
  "exit 1"

if errorlevel 1 (
  echo Server failed to start on port %PORT%.
  pause
  exit /b 1
)

start "" "http://127.0.0.1:%PORT%/?launch=%RANDOM%%RANDOM%"
