' Close LUMINA AI — Hidden stop wrapper (double-click entry point)
' Stops only LUMINA frontend and backend processes.
' Does NOT stop Docker Desktop or unrelated processes.
Option Explicit

Dim fso, shell, scriptDir, repoRoot, psScript, logDir, cmd, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(fso.GetParentFolderName(scriptDir))
psScript = scriptDir & "\LuminaLauncher.ps1"
logDir = repoRoot & "\.lumina-runtime\logs"

If Not fso.FileExists(psScript) Then
    MsgBox "LUMINA launcher script was not found:" & vbCrLf & psScript, vbCritical, "LUMINA AI"
    WScript.Quit 1
End If

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psScript & """ -Action stop"

rc = shell.Run(cmd, 0, True)

If rc <> 0 Then
    MsgBox "Close LUMINA reported an issue (exit code " & rc & ")." & vbCrLf & _
           "Check the launcher log:" & vbCrLf & logDir & "\launcher.log", vbExclamation, "LUMINA AI"
    WScript.Quit rc
End If

WScript.Quit 0