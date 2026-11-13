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
echo Double-click that. A command window should not appear.
pause
