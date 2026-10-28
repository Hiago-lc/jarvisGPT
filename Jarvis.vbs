' Abre o Jarvis sem a janela preta do terminal. É o que o atalho
' "Jarvis HAIZEN" da área de trabalho chama.
Option Explicit
Dim fso, sh, pasta, py, arq, f, http, aberto, base, pastas, p

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
pasta = fso.GetParentFolderName(WScript.ScriptFullName)

' Já aberto? A central do Jarvis responde na porta 8765.
aberto = False
On Error Resume Next
Set http = CreateObject("MSXML2.XMLHTTP")
http.Open "GET", "http://127.0.0.1:8765/api/sistema/versao", False
http.setRequestHeader "X-Central", "1"
http.Send
If Err.Number = 0 Then
  If http.Status = 200 Then aberto = True
End If
Err.Clear
On Error GoTo 0
If aberto Then
  If MsgBox("O Jarvis já está aberto. Abrir outra janela mesmo assim?", vbYesNo + vbQuestion, "Jarvis") <> vbYes Then WScript.Quit
End If

' O Python que o Jarvis usou da última vez (o start_local.py anota aqui).
py = ""
arq = pasta & "\config\python_local.txt"
If fso.FileExists(arq) Then
  Set f = fso.OpenTextFile(arq, 1)
  If Not f.AtEndOfStream Then py = Trim(f.ReadLine)
  f.Close
  If py <> "" Then
    If Not fso.FileExists(py) Then py = ""
  End If
End If

' Senão: o mesmo Python do início automático com o Windows.
If py = "" Then
  arq = sh.ExpandEnvironmentStrings("%APPDATA%") & "\Microsoft\Windows\Start Menu\Programs\Startup\Jarvis HAIZEN.cmd"
  If fso.FileExists(arq) Then
    Set f = fso.OpenTextFile(arq, 1)
    Do Until f.AtEndOfStream
      p = f.ReadLine
      If Left(LCase(p), 9) = "start """" " Then
        p = Mid(p, 10)
        If Left(p, 1) = """" Then
          p = Mid(p, 2, InStr(2, p, """") - 2)
          If fso.FileExists(p) Then py = p
        End If
      End If
    Loop
    f.Close
  End If
End If

' Sem a anotação: o inicializador do Python (pyw) ou o pythonw mais novo.
If py = "" Then
  If fso.FileExists(sh.ExpandEnvironmentStrings("%WINDIR%") & "\pyw.exe") Then
    py = sh.ExpandEnvironmentStrings("%WINDIR%") & "\pyw.exe"
  ElseIf fso.FileExists(sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Launcher\pyw.exe") Then
    py = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Launcher\pyw.exe"
  Else
    base = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
    If fso.FolderExists(base) Then
      For Each p In fso.GetFolder(base).SubFolders
        If fso.FileExists(p.Path & "\pythonw.exe") Then py = p.Path & "\pythonw.exe"
      Next
    End If
  End If
End If
If py = "" Then py = "pythonw.exe"

sh.CurrentDirectory = pasta
On Error Resume Next
sh.Run """" & py & """ """ & pasta & "\start_local.py""", 0, False
If Err.Number <> 0 Then
  MsgBox "Não consegui abrir o Jarvis: o Python não foi encontrado." & vbCrLf & _
         "Abra uma vez pelo PyCharm ou pelo terminal (python start_local.py) e tente de novo.", vbExclamation, "Jarvis"
End If
