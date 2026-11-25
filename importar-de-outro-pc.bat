@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  Jarvis: importar de outro computador
echo ============================================================
echo Feche o Jarvis antes (icone perto do relogio, Sair).
echo Procura o pacote mais novo em "Meu Drive\JARVIS - migracao".
echo Para usar outro arquivo, arraste o .jarvispack para cima deste .bat.
echo.
set PY=python
if exist "config\python_local.txt" for /f "usebackq delims=" %%p in ("config\python_local.txt") do set PY=%%p
"%PY:pythonw.exe=python.exe%" migrar.py importar %1
echo.
pause
