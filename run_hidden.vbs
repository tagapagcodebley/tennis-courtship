' Launches run_watcher.ps1 with zero visible window. Unlike PowerShell's
' own -WindowStyle Hidden (which still briefly allocates a console before
' hiding it -- causing a visible flash that can steal foreground focus),
' WScript.Shell.Run with style 0 never creates a console window at all.
Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & scriptDir & "\run_watcher.ps1"""

' 0 = hidden window, True = wait for completion and relay its exit code
exitCode = objShell.Run(cmd, 0, True)
WScript.Quit exitCode
