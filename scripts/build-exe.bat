@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Create the virtual environment first. The README explains how.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 (
  echo The build programs did not install. The exe was not built.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-voice.txt
if errorlevel 1 (
  echo The voice programs did not install. The exe was not built.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller packaging\babysitter.spec --noconfirm
echo.
echo The program is one file: dist\BabySitter.exe
echo Copy that file to the desktop, or any other folder. It does not need this folder beside it.
echo Settings stay in %%LOCALAPPDATA%%\BabySitter.
echo A command window should not appear when you double-click the file.
echo.
echo Double-click scripts\desktop-icon.bat for an icon that opens dist\BabySitter.exe.
echo After a later git pull, run this build again. That same icon opens the new build.
echo A file copied onto the desktop stays as it was until you copy it again.
echo.
set /p COPYDESKTOP=Type Y to copy the file itself to the desktop, or press Enter to skip: 
if /I "%COPYDESKTOP%"=="Y" (
  copy /Y "dist\BabySitter.exe" "%USERPROFILE%\Desktop\BabySitter.exe"
  if errorlevel 1 (
    echo The copy did not finish. dist\BabySitter.exe is still the file to move.
  ) else (
    echo Copied to the desktop.
  )
)
pause
