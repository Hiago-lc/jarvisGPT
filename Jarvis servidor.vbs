' Abre o Jarvis do SERVIDOR numa janela propria (Edge ou Chrome, como aplicativo), com voz.
' Na primeira vez pergunta o endereco (ex.: https://jarvis.seudominio.com.br) e guarda em
' config\servidor_url.txt. O login do Google fica salvo nesta janela.
Option Explicit
Dim fso, sh, pasta, arq, f, url, perfil, exe, candidatos, c

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
pasta = fso.GetParentFolderName(WScript.ScriptFullName)
arq = pasta & "\config\servidor_url.txt"

url = ""
If fso.FileExists(arq) Then
  Set f = fso.OpenTextFile(arq, 1)
  If Not f.AtEndOfStream Then url = Trim(f.ReadLine)
  f.Close
End If
If url = "" Then
  url = Trim(InputBox("Endereco do Jarvis no servidor (ex.: https://jarvis.seudominio.com.br):", "Jarvis no servidor", "https://"))
  If url = "" Or url = "https://" Then WScript.Quit
  If Not fso.FolderExists(pasta & "\config") Then fso.CreateFolder(pasta & "\config")
  Set f = fso.CreateTextFile(arq, True)
  f.WriteLine url
  f.Close
End If

perfil = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\JarvisGPT\janela-servidor"
candidatos = Array( _
  sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Microsoft\Edge\Application\msedge.exe", _
  sh.ExpandEnvironmentStrings("%ProgramFiles%") & "\Microsoft\Edge\Application\msedge.exe", _
  sh.ExpandEnvironmentStrings("%ProgramFiles%") & "\Google\Chrome\Application\chrome.exe", _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Google\Chrome\Application\chrome.exe")
exe = ""
For Each c In candidatos
  If exe = "" And fso.FileExists(c) Then exe = c
Next
If exe = "" Then
  sh.Run url
Else
  sh.Run """" & exe & """ --app=" & url & " --user-data-dir=""" & perfil & """ --window-size=1280,860 --no-first-run --no-default-browser-check", 1, False
End If
