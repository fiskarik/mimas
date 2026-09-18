@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=
if not exist ".venv\Scripts\python.exe" (
  echo Не найдено окружение .venv.
  echo Сначала запустите setup.ps1.
  pause
  exit /b 1
)
echo Запускаю Автособес...
echo Откройте http://localhost:3000
echo Ключ работодателя: demo-company
echo Для остановки закройте это окно или нажмите Ctrl+C.
".venv\Scripts\python.exe" run_demo.py
pause