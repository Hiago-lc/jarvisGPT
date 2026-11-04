@echo off
title Conectar o Jarvis ao Meta Ads
set "C="
for %%P in ("%USERPROFILE%\.local\bin\claude.exe" "%USERPROFILE%\.claude\local\claude.exe" "%USERPROFILE%\.claude\local\claude.cmd" "%APPDATA%\npm\claude.cmd" "%LOCALAPPDATA%\Programs\claude\claude.exe" "%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe") do (
  if not defined C if exist %%P set "C=%%~P"
)
if not defined C for /f "delims=" %%W in ('where claude 2^>nul') do if not defined C set "C=%%W"
if not defined C (
  echo.
  echo Nao achei o Claude Code neste PC. Rode antes o conectar-claude.bat.
  echo.
  pause
  exit /b 1
)
echo.
echo ================================================================
echo  Conectar o Jarvis ao Meta Ads (conector oficial da Meta)
echo ================================================================
echo.
echo PASSO 1 - um app seu na Meta (so na primeira vez)
echo   1. Abra https://developers.facebook.com/apps e clique em "Criar app".
echo   2. Escolha o tipo "Empresa" (Business) e ligue ao portfolio da HAIZEN.
echo   3. Em "Casos de uso", adicione: "Create ^& manage ads with ads MCP server".
echo   4. Em "Login do Facebook para Empresas" ^> Configuracoes, em
echo      "URIs de redirecionamento do OAuth validos", coloque:
echo          http://localhost:53682/callback
echo   5. Copie o "ID do app" (em Configuracoes do app ^> Basico).
echo.
set "APPID="
set /p APPID=Cole aqui o ID do app e aperte Enter: 
if "%APPID%"=="" (
  echo Sem o ID do app nao da para conectar.
  pause
  exit /b 1
)
echo.
set "SEGREDO="
set /p SEGREDO=A Meta pede a Chave Secreta do app? (deixe vazio se nao souber; cole se o login reclamar): 
"%C%" mcp remove meta-ads -s user >nul 2>nul
if "%SEGREDO%"=="" (
  "%C%" mcp add --transport http --scope user --client-id %APPID% --callback-port 53682 meta-ads https://mcp.facebook.com/ads
) else (
  set "MCP_CLIENT_SECRET=%SEGREDO%"
  "%C%" mcp add --transport http --scope user --client-id %APPID% --client-secret --callback-port 53682 meta-ads https://mcp.facebook.com/ads
)
if errorlevel 1 (
  echo.
  echo Nao consegui cadastrar o conector. Tire um print desta janela e mande ao Claude.
  pause
  exit /b 1
)
echo.
echo PASSO 2 - entrar no Facebook
echo   Agora o Claude Code vai abrir. Nele:
echo   1. digite /mcp e aperte Enter
echo   2. escolha "meta-ads" e depois "Authenticate"
echo   3. no navegador, entre no Facebook e MARQUE as contas de anuncio
echo      dos clientes que o Jarvis vai analisar
echo   4. quando aparecer "connected", feche o Claude Code (Ctrl+C duas vezes)
echo.
echo PASSO 3 - na central do Jarvis, tela Trafego, clique em
echo   "Ja fiz o login, buscar minhas contas".
echo.
echo O acesso da Meta vence a cada ~60 dias: quando o Jarvis avisar,
echo rode este arquivo de novo (pode pular o passo 1).
echo.
pause
"%C%"
