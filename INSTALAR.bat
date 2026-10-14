@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente Python 3.11...
  py -3.11 -m venv ".venv"
  if errorlevel 1 goto :erro
)

echo Atualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :erro

echo Instalando/reparando dependencias...
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto :erro

".venv\Scripts\python.exe" -c "import yaml, requests, PIL, numpy; print('Dependencias Python: OK')"
if errorlevel 1 goto :erro

echo.
echo INSTALACAO CONCLUIDA.
pause
exit /b 0

:erro
echo.
echo ERRO NA INSTALACAO.
echo Se esta pasta foi movida com uma .venv antiga, apague somente a pasta .venv e rode INSTALAR.bat novamente.
pause
exit /b 1
