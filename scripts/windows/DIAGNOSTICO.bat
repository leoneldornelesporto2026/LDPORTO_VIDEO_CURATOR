@echo off
setlocal
cd /d "%~dp0..\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\windows\DIAGNOSTICO.py"
) else (
  py -3.11 "scripts\windows\DIAGNOSTICO.py"
)
set "EXITCODE=%ERRORLEVEL%"
pause
exit /b %EXITCODE%
