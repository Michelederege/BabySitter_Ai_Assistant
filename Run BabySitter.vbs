' Starts BabySitter with no command window.
' If nothing appears, double-click "Show errors.bat" instead and copy the text.
Option Explicit
Dim fso, shell, root, env, venvPy, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
Set env = shell.Environment("PROCESS")
env("PYTHONPATH") = root & "\src"
venvPy = root & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(venvPy) Then
  cmd = """" & venvPy & """ -m babysitter"
Else
  cmd = "pyw -3.12 -m babysitter"
End If
On Error Resume Next
shell.Run cmd, 0, False
If Err.Number <> 0 Then
  MsgBox "BabySitter could not start." & vbCrLf & vbCrLf & _
    "Double-click Show errors.bat in this folder and send me the exact text." & vbCrLf & vbCrLf & _
    Err.Description, vbCritical, "BabySitter"
End If
