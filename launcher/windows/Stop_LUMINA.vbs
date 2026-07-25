' LUMINA silent stop launcher (double-click).
' Stops only LUMINA-owned processes.
Option Explicit

Dim fso, shell, scriptDir, repoRoot, pythonCmd, launcher, logDir, cmd, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(scriptDir)
launcher = repoRoot & "\launcher\lumina_launcher.py"
logDir = repoRoot & "\.lumina-runtime\logs"

If Not fso.FileExists(launcher) Then
  MsgBox "LUMINA launcher was not found:" & vbCrLf & launcher, vbCritical, "LUMINA"
  WScript.Quit 1
End If

pythonCmd = ResolvePython()
If pythonCmd = "" Then
  MsgBox "Python 3.11+ was not found on PATH.", vbCritical, "LUMINA"
  WScript.Quit 3
End If

cmd = """" & pythonCmd & """ """ & launcher & """ stop"
' When pythonCmd is "py -3.11", quoting breaks — use cmd.exe
If InStr(pythonCmd, " ") > 0 Then
  cmd = "cmd /c " & pythonCmd & " """ & launcher & """ stop"
End If
rc = shell.Run(cmd, 0, True)

If rc <> 0 Then
  MsgBox "LUMINA stop reported an issue (exit code " & rc & ")." & vbCrLf & _
         "Check logs in:" & vbCrLf & logDir, vbExclamation, "LUMINA"
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
