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

echo Instalando dependencias com "%PYTHON_EXE%" %PYTHON_ARGS%
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERRO: falha ao instalar dependencias. Consulte docs\INSTALACAO_WINDOWS.md
  pause
  exit /b 1
)
"%PYTHON_EXE%" %PYTHON_ARGS% -c "from PIL import Image; import yt_dlp; print('Dependencias OK')"
if errorlevel 1 (
  echo ERRO: Pillow ou yt-dlp indisponivel neste Python.
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo AVISO: FFmpeg ausente do PATH.
  echo Opcao: winget install --id Gyan.FFmpeg -e
)
where ffprobe >nul 2>nul
if errorlevel 1 echo AVISO: FFprobe ausente do PATH.
echo Instalacao concluida.
pause
endlocal
