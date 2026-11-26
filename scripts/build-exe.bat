@echo off
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src"

if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python 3.12 virtual environment .venv...
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Could not create .venv with Python 3.12. Install Python 3.12 first, or see README.md.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo The core libraries did not install. The exe was not built.
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

".venv\Scripts\python.exe" -c "import babysitter.app, babysitter.ui.shell"
if errorlevel 1 (
  echo BabySitter failed its startup import check. Fix the error above before building.
  pause
  exit /b 1
)

tasklist /FI "IMAGENAME eq BabySitter.exe" 2>NUL | find /I "BabySitter.exe" >NUL
if not errorlevel 1 (
  echo Closing running BabySitter.exe so Windows unlocks dist\BabySitter.exe...
  taskkill /IM BabySitter.exe /T /F >NUL 2>NUL
  timeout /t 1 /nobreak >NUL
)

if exist "dist\BabySitter.exe" (
  del /F /Q "dist\BabySitter.exe" >NUL 2>NUL
  if exist "dist\BabySitter.exe" (
    echo Windows is still locking dist\BabySitter.exe.
    echo Right-click the BabySitter tray icon, choose Quit, and run this build again.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m PyInstaller packaging\babysitter.spec --noconfirm
if errorlevel 1 (
  echo.
  echo PyInstaller failed. Scroll up and copy the error lines above.
  echo dist\BabySitter.exe was not built.
  pause
  exit /b 1
)
if not exist "dist\BabySitter.exe" (
  echo.
  echo PyInstaller finished, but dist\BabySitter.exe was not found.
  pause
  exit /b 1
)

echo.
echo Built successfully: dist\BabySitter.exe
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
    echo The copy did not finish (close the desktop BabySitter.exe if it is open in the tray).
    echo dist\BabySitter.exe is ready to move once closed.
  ) else (
    echo Copied to the desktop.
  )
)
pause
