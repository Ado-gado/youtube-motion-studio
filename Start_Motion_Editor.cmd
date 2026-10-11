@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install the package first: python scripts/install.py --project-root .
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import tkinterdnd2" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install --no-cache-dir -r requirements-editor.txt
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
start "" ".venv\Scripts\pythonw.exe" -m editor.app
