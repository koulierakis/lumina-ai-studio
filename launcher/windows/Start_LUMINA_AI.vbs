' LUMINA AI — Hidden launcher wrapper (double-click entry point)
' Runs the PowerShell launcher with no visible terminal window.
Option Explicit

Dim fso, shell, scriptDir, repoRoot, psScript, logDir, cmd, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(fso.GetParentFolderName(scriptDir))
psScript = scriptDir & "\LuminaLauncher.ps1"
logDir = repoRoot & "\.lumina-runtime\logs"

' Ensure log directory exists
If Not fso.FolderExists(repoRoot & "\.lumina-runtime") Then
    fso.CreateFolder repoRoot & "\.lumina-runtime"
End If
If Not fso.FolderExists(logDir) Then
    fso.CreateFolder logDir
End If

' Verify PowerShell script exists
If Not fso.FileExists(psScript) Then
    MsgBox "LUMINA launcher script was not found:" & vbCrLf & psScript, vbCritical, "LUMINA AI"
    WScript.Quit 1
End If

' Run PowerShell with -ExecutionPolicy Bypass (scoped to this process only)
' -NoProfile avoids loading user PS profile (faster, no side effects)
' -WindowStyle Hidden prevents terminal flash
' -File with quoted path handles spaces in Windows paths
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psScript & """ -Action start"

rc = shell.Run(cmd, 0, True)

' Exit code 0 = success, anything else = failure
If rc <> 0 Then
    MsgBox "LUMINA AI failed to start (Exit Code " & rc & ")." & vbCrLf & vbCrLf & _
           "Check the launcher log:" & vbCrLf & logDir & "\launcher.log", vbCritical, "LUMINA AI"
    WScript.Quit rc
End If

WScript.Quit 0