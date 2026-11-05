@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m pip install -r requirements.txt
) else (
  python -m pip install -r requirements.txt
)
if errorlevel 1 (
  echo Falha ao instalar Pillow. Consulte docs\INSTALACAO_WINDOWS.md
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo.
  echo FFmpeg nao foi encontrado no PATH.
  echo Instale FFmpeg e FFprobe separadamente antes de renderizar.
  echo Sugestao: winget install --id Gyan.FFmpeg -e
) else (
  ffmpeg -version | findstr /b "ffmpeg version"
)
echo.
echo Instalacao Python concluida. Para abrir: INICIAR_WINDOWS.bat
pause
endlocal
