@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install the package first. See LOCAL_RENDER.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 "scripts\local_worker.py" retry-errors
pause
