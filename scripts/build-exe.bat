@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Create the virtual environment first. The README explains how.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
".venv\Scripts\python.exe" -m PyInstaller packaging\babysitter.spec --noconfirm
echo.
echo The windowed app is dist\BabySitter\BabySitter.exe
echo Double-click scripts\desktop-icon.bat to put that app on the desktop.
echo After a later git pull, run this build again. The same desktop icon opens the new build.
pause
