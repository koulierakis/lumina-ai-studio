' Create Desktop shortcuts for Start LUMINA and Stop LUMINA.
Option Explicit

Dim fso, shell, scriptDir, repoRoot, desktop, link, startVbs, stopVbs
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(scriptDir)
desktop = shell.SpecialFolders("Desktop")
startVbs = scriptDir & "\Start_LUMINA.vbs"
stopVbs = scriptDir & "\Stop_LUMINA.vbs"

If Not fso.FileExists(startVbs) Or Not fso.FileExists(stopVbs) Then
  MsgBox "Launcher VBS files are missing in:" & vbCrLf & scriptDir, vbCritical, "LUMINA"
  WScript.Quit 1
End If

Set link = shell.CreateShortcut(desktop & "\Start LUMINA.lnk")
link.TargetPath = "wscript.exe"
link.Arguments = """" & startVbs & """"
link.WorkingDirectory = repoRoot
link.WindowStyle = 7
link.Description = "Start LUMINA local runtime"
link.Save

Set link = shell.CreateShortcut(desktop & "\Stop LUMINA.lnk")
link.TargetPath = "wscript.exe"
link.Arguments = """" & stopVbs & """"
link.WorkingDirectory = repoRoot
link.WindowStyle = 7
link.Description = "Stop LUMINA-owned processes safely"
link.Save

MsgBox "Desktop shortcuts created:" & vbCrLf & _
       "- Start LUMINA" & vbCrLf & _
       "- Stop LUMINA", vbInformation, "LUMINA"
