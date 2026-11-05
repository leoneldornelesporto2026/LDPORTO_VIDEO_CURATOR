@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 launch_gui.py
) else (
  python launch_gui.py
)
if errorlevel 1 (
  echo.
  echo ERRO: verifique a instalacao de Python 3.11+, Pillow e FFmpeg.
  echo Consulte docs\INSTALACAO_WINDOWS.md
  pause
)
endlocal
