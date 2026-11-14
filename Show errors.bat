@echo off
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
echo Starting BabySitter in this window so any error stays on screen.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo The Python folder .venv is missing.
  echo Run these two lines in this folder, then try again:
  echo   py -3.12 -m venv .venv
  echo   .venv\Scripts\python -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m babysitter
echo.
echo If you see an error above, copy the whole text and send it to me.
pause
