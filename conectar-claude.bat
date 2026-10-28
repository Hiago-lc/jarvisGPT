@echo off
title Conectar o Claude Code a sua conta
set "C="
for %%P in ("%USERPROFILE%\.local\bin\claude.exe" "%USERPROFILE%\.claude\local\claude.exe" "%USERPROFILE%\.claude\local\claude.cmd" "%APPDATA%\npm\claude.cmd" "%LOCALAPPDATA%\Programs\claude\claude.exe" "%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe") do (
  if not defined C if exist %%P set "C=%%~P"
)
if not defined C for /f "delims=" %%W in ('where claude 2^>nul') do if not defined C set "C=%%W"
if not defined C (
  echo.
  echo Nao achei o Claude Code neste PC.
  echo Instale pelo PowerShell com:  irm https://claude.ai/install.ps1 ^| iex
  echo.
  pause
  exit /b 1
)
echo.
echo Achei o Claude Code em:
echo   %C%
echo.
echo Quando ele abrir:
echo   1. digite /login e aperte Enter
echo   2. escolha a conta Claude com assinatura (NAO a opcao de chave de API)
echo   3. autorize no navegador que abrir
echo   4. depois feche esta janela
echo.
pause
"%C%"
