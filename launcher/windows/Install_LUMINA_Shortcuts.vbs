' Create Desktop shortcuts for LUMINA AI and Close LUMINA.
' Double-click this script to install the desktop shortcuts.
Option Explicit

Dim fso, shell, scriptDir, repoRoot, desktop
Dim startVbs, closeVbs, link, iconPath

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(fso.GetParentFolderName(scriptDir))
desktop = shell.SpecialFolders("Desktop")
startVbs = scriptDir & "\Start_LUMINA_AI.vbs"
closeVbs = scriptDir & "\Close_LUMINA_AI.vbs"

' Verify VBS launchers exist
If Not fso.FileExists(startVbs) Then
    MsgBox "Start launcher not found:" & vbCrLf & startVbs, vbCritical, "LUMINA AI"
    WScript.Quit 1
End If
If Not fso.FileExists(closeVbs) Then
    MsgBox "Close launcher not found:" & vbCrLf & closeVbs, vbCritical, "LUMINA AI"
    WScript.Quit 1
End If

' Use a built-in Windows icon if no custom icon exists
' Look for favicon.ico in frontend/public, fall back to shell32.dll icon 13 (document)
iconPath = repoRoot & "\frontend\public\favicon.ico"
If Not fso.FileExists(iconPath) Then
    ' Use the Windows default application icon (shell32.dll, index 13)
    iconPath = "shell32.dll,13"
End If

' ─── Create "LUMINA AI" shortcut ───
Set link = shell.CreateShortcut(desktop & "\LUMINA AI.lnk")
link.TargetPath = "wscript.exe"
link.Arguments = """" & startVbs & """"
link.WorkingDirectory = repoRoot
link.WindowStyle = 7  ' Minimized — no visible terminal
link.Description = "Start LUMINA AI Operating System — backend, frontend, and Docker services"
link.IconLocation = iconPath
link.Save

' ─── Create "Close LUMINA" shortcut ───
Set link = shell.CreateShortcut(desktop & "\Close LUMINA.lnk")
link.TargetPath = "wscript.exe"
link.Arguments = """" & closeVbs & """"
link.WorkingDirectory = repoRoot
link.WindowStyle = 7  ' Minimized — no visible terminal
link.Description = "Safely stop LUMINA frontend and backend processes"
link.IconLocation = "shell32.dll,132"  ' Stop/shutdown icon
link.Save

MsgBox "Desktop shortcuts created successfully:" & vbCrLf & vbCrLf & _
       "  • LUMINA AI    — Double-click to start the application" & vbCrLf & _
       "  • Close LUMINA — Double-click to stop the application" & vbCrLf & vbCrLf & _
       "The shortcuts will:" & vbCrLf & _
       "  - Start Docker Desktop if needed" & vbCrLf & _
       "  - Start Redis and Qdrant containers" & vbCrLf & _
       "  - Start backend and frontend" & vbCrLf & _
       "  - Open the app in your browser" & vbCrLf & _
       "  - Avoid duplicate processes", vbInformation, "LUMINA AI"