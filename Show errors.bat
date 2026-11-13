@echo off
cd /d "%~dp0"
set PYTHONPATH=src
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m babysitter
) else (
  py -3.12 -m babysitter
)
echo.
echo If you see an error above, copy the whole text and send it to me.
pause
