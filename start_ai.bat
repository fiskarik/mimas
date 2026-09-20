@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.ps1 first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m cli.main --live
pause
