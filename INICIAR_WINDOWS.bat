@echo off
setlocal
cd /d "%~dp0"
rem Use the SAME Python to install packages and launch the Studio.
set "PYTHON_EXE="
set "PYTHON_ARGS="
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "PYTHON_EXE=%VIRTUAL_ENV%\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
  )
)
if not defined PYTHON_EXE (
  echo ERRO: Python 3.11+ nao encontrado.
  pause
  exit /b 1
)

"%PYTHON_EXE%" %PYTHON_ARGS% -c "from PIL import Image; import yt_dlp"
if errorlevel 1 (
  echo ERRO: dependencias ausentes. Execute INSTALAR_WINDOWS.bat.
  pause
  exit /b 1
)
"%PYTHON_EXE%" %PYTHON_ARGS% launch_gui.py
if errorlevel 1 (
  echo ERRO: falha ao iniciar Studio. Consulte docs\INSTALACAO_WINDOWS.md.
  pause
  exit /b 1
)
endlocal
