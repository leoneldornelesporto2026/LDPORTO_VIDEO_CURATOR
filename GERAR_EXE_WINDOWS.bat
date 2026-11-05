@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m pip install pyinstaller
  if errorlevel 1 exit /b 1
  py -3 -m PyInstaller --noconfirm --clean --onedir --windowed --name LDPORTO_Video_Curator_Studio --add-data "example\CURADORIA_R57.zip;example" launch_gui.py
) else (
  python -m pip install pyinstaller
  if errorlevel 1 exit /b 1
  python -m PyInstaller --noconfirm --clean --onedir --windowed --name LDPORTO_Video_Curator_Studio --add-data "example\CURADORIA_R57.zip;example" launch_gui.py
)
if errorlevel 1 (
  echo Erro no build do exe.
  pause
  exit /b 1
)
echo.
echo Pasta gerada: dist\LDPORTO_Video_Curator_Studio
 echo ATENCAO: FFmpeg ainda precisa estar instalado no PATH do Windows.
pause
endlocal
