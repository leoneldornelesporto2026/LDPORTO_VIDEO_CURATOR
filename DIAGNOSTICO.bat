@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  call ".venv\Scripts\activate.bat"
  python DIAGNOSTICO.py
) else (
  py -3.11 DIAGNOSTICO.py
)
pause
