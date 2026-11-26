@echo off
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
if not exist ".venv\Scripts\python.exe" (
  echo BabySitter did not start because its Python folder is missing.
  echo.
  echo In this same folder, run these two lines, one at a time:
  echo   py -3.12 -m venv .venv
  echo   .venv\Scripts\python -m pip install -r requirements.txt
  echo.
  echo Then double-click this file again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import babysitter.app, babysitter.ui.shell"
if errorlevel 1 (
  echo.
  echo BabySitter could not start. Copy the text above.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m babysitter
