@echo off
cd /d "%~dp0.."
if not exist "dist\BabySitter.exe" (
  echo Build the windowed app first. Double-click scripts\build-exe.bat
  pause
  exit /b 1
)
if not exist "assets\icon.ico" (
  echo The BabySitter icon is missing from assets\icon.ico
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%CD%'; $shell = New-Object -ComObject WScript.Shell; $desk = [Environment]::GetFolderPath('Desktop'); $link = $shell.CreateShortcut((Join-Path $desk 'BabySitter.lnk')); $link.TargetPath = (Resolve-Path 'dist\BabySitter.exe').Path; $link.WorkingDirectory = (Resolve-Path 'dist').Path; $link.IconLocation = ((Resolve-Path 'assets\icon.ico').Path + ',0'); $link.Description = 'BabySitter'; $link.Save()"
if errorlevel 1 (
  echo The desktop icon was not created.
  pause
  exit /b 1
)
echo.
echo BabySitter is on the desktop. It opens dist\BabySitter.exe
echo After git pull, double-click scripts\build-exe.bat again.
echo The same desktop icon then opens the new build.
echo Reminders and settings stay in %%LOCALAPPDATA%%\BabySitter
pause
