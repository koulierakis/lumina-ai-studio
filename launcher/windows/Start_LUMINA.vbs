' Fixed Start launcher that handles "py -3.11" correctly via cmd.exe
Option Explicit

Dim fso, shell, scriptDir, repoRoot, launcher, logDir, pythonCmd, cmd, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(scriptDir)
launcher = repoRoot & "\launcher\lumina_launcher.py"
logDir = repoRoot & "\.lumina-runtime\logs"

If Not fso.FolderExists(repoRoot & "\.lumina-runtime") Then fso.CreateFolder repoRoot & "\.lumina-runtime"
If Not fso.FolderExists(logDir) Then fso.CreateFolder logDir

If Not fso.FileExists(launcher) Then
  MsgBox "LUMINA launcher was not found:" & vbCrLf & launcher, vbCritical, "LUMINA"
  WScript.Quit 1
End If

pythonCmd = ResolvePython()
If pythonCmd = "" Then
  MsgBox "Python 3.11+ was not found on PATH. Install Python and try again.", vbCritical, "LUMINA"
  WScript.Quit 3
End If

cmd = "cmd /c " & pythonCmd & " """ & launcher & """ start"
rc = shell.Run(cmd, 0, True)

If rc = 2 Then
  shell.Run "http://localhost:3000/", 1, False
  WScript.Quit 0
End If

If rc <> 0 Then
  MsgBox "LUMINA failed to start (exit code " & rc & ")." & vbCrLf & vbCrLf & _
         "Check logs in:" & vbCrLf & logDir & vbCrLf & vbCrLf & _
         "Or run: python launcher\lumina_launcher.py doctor", vbCritical, "LUMINA"
  WScript.Quit rc
End If

WScript.Quit 0

Function ResolvePython()
  Dim candidates, i, probe
  candidates = Array("py -3.11", "py -3", "python", "python3")
  For i = 0 To UBound(candidates)
    probe = "cmd /c " & candidates(i) & " -c ""import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"""
    If shell.Run(probe, 0, True) = 0 Then
      ResolvePython = candidates(i)
      Exit Function
    End If
  Next
  ResolvePython = ""
End Function
