@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install the package first. See LOCAL_RENDER.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 "scripts\check_local_font.py"
set "motion_font_result=%errorlevel%"
pause
exit /b %motion_font_result%
