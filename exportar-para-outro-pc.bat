@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  Jarvis: exportar tudo para outro computador
echo ============================================================
echo Cria um arquivo .jarvispack (protegido por senha) com o banco,
echo as configuracoes, os tokens e a memoria. Vai para a pasta
echo "JARVIS - migracao" do seu Google Drive.
echo.
set PY=python
if exist "config\python_local.txt" for /f "usebackq delims=" %%p in ("config\python_local.txt") do set PY=%%p
"%PY:pythonw.exe=python.exe%" migrar.py exportar
echo.
pause
