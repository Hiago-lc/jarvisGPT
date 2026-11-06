@echo off
title Preparar a producao dos agentes (Jarvis)
cd /d "%~dp0"
set "PY="
if exist "config\python_local.txt" set /p PY=<"config\python_local.txt"
if defined PY set "PY=%PY:pythonw.exe=python.exe%"
if not defined PY set "PY=python"
echo Usando: %PY%
echo.
echo 1/3  Instalando o ffmpeg para os videos...
"%PY%" -m pip install --upgrade imageio-ffmpeg
echo.
echo 2/3  Conferindo o navegador para gerar as imagens...
"%PY%" -m playwright install chromium
echo.
echo 3/3  Verificando tudo:
"%PY%" "%~dp0haizen\producao\ferramentas.py" verificar
echo.
echo Pronto. Se alguma linha acima disser FALTA, me mande um print.
pause
