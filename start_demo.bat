@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=
if not exist ".venv\Scripts\python.exe" (
  echo Python environment .venv was not found.
  echo Run setup.ps1 first.
  pause
  exit /b 1
)
echo Starting Autosobes...
echo Open http://localhost:3000
echo Company key: demo-company
echo Close this window or press Ctrl+C to stop.
".venv\Scripts\python.exe" run_demo.py
pause
