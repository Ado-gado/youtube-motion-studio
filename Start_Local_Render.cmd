@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start_Local_Render.ps1" %*
if errorlevel 1 pause
