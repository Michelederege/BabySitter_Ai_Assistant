' Starts BabySitter with no command window.
' pythonw already has no console, so the window style stays 1 (normal).
' Style 0 hides the program. A double-click then looks like nothing happened.
' If the window still does not open, double-click "Run BabySitter.bat".
Option Explicit
Dim fso, shell, root, env, venvPy, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
Set env = shell.Environment("PROCESS")
env("PYTHONPATH") = root & "\src"
venvPy = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(venvPy) Then
  MsgBox "BabySitter did not start because its Python folder is missing." & vbCrLf & vbCrLf & _
    "Open this folder, click the address bar, type cmd, and press Enter." & vbCrLf & _
    "Then run these two lines, one at a time:" & vbCrLf & vbCrLf & _
    "py -3.12 -m venv .venv" & vbCrLf & _
    ".venv\Scripts\python -m pip install -r requirements.txt" & vbCrLf & vbCrLf & _
    "When that finishes, double-click Run BabySitter.vbs again.", _
    vbCritical, "BabySitter"
  WScript.Quit 1
End If
cmd = """" & venvPy & """ -m babysitter"
shell.Run cmd, 1, False
