' Cria (ou recria) o atalho "Jarvis HAIZEN" na área de trabalho,
' com o ícone do Jarvis. Dê dois cliques neste arquivo.
Option Explicit
Dim fso, sh, pasta, lnk
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
pasta = fso.GetParentFolderName(WScript.ScriptFullName)
Set lnk = sh.CreateShortcut(sh.SpecialFolders("Desktop") & "\Jarvis HAIZEN.lnk")
lnk.TargetPath = sh.ExpandEnvironmentStrings("%WINDIR%") & "\System32\wscript.exe"
lnk.Arguments = """" & pasta & "\Jarvis.vbs"""
lnk.WorkingDirectory = pasta
lnk.IconLocation = pasta & "\config\jarvis.ico,0"
lnk.Description = "Abre o Jarvis"
lnk.Save
MsgBox "Pronto: o atalho Jarvis HAIZEN está na área de trabalho.", vbInformation, "Jarvis"
