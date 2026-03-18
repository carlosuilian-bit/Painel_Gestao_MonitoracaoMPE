@echo off
setlocal
cd /d "%~dp0"

if not defined PAINEL_HOST set "PAINEL_HOST=0.0.0.0"
if not defined PAINEL_PORT set "PAINEL_PORT=4173"

echo Iniciando servidor em %PAINEL_HOST%:%PAINEL_PORT%...
python "%~dp0server.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Falha ao iniciar o servidor.
  echo Verifique o IP configurado em PAINEL_HOST e se o Python esta instalado.
  pause
)

exit /b %EXIT_CODE%
