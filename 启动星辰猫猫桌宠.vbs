Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = dir
WshShell.Run """" & dir & "\.venv\Scripts\pythonw.exe"" """ & dir & "\main.py""", 0, False
