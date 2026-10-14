@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Ambiente Python nao encontrado. Criando/instalando agora...
  call "INSTALAR.bat"
  if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -c "import yaml, requests, PIL, numpy" >nul 2>&1
if errorlevel 1 (
  echo Dependencias incompletas. Reparando ambiente...
  ".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
  if errorlevel 1 (
    echo.
    echo ERRO: nao foi possivel instalar as dependencias.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" "app.py"
if errorlevel 1 (
  echo.
  echo O Curator terminou com erro. Veja a mensagem acima.
  pause
)
