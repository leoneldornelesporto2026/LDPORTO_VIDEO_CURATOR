@echo off
setlocal
cd /d "%~dp0..\.."
if "%~1"=="" (
  echo Uso: scripts\windows\TESTAR_1_CORTE.bat URL [RANK]
  echo Exemplo: scripts\windows\TESTAR_1_CORTE.bat https://www.youtube.com/watch?v=wA1ipztt54c 1
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente nao encontrado. Execute INSTALAR.bat na raiz do projeto.
  pause
  exit /b 1
)
set "RANK=%~2"
if "%RANK%"=="" set "RANK=1"
".venv\Scripts\python.exe" "cli.py" "%~1" --test-one %RANK%
set "EXITCODE=%ERRORLEVEL%"
pause
exit /b %EXITCODE%
