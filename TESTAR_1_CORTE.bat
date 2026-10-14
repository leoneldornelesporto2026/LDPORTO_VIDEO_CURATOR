@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Uso: TESTAR_1_CORTE.bat URL [RANK]
  echo Exemplo: TESTAR_1_CORTE.bat https://www.youtube.com/watch?v=wA1ipztt54c 1
  pause
  exit /b 1
)
set RANK=%~2
if "%RANK%"=="" set RANK=1
call ".venv\Scripts\activate.bat"
python cli.py "%~1" --test-one %RANK%
pause
