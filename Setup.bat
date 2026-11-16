@echo off
cd /d "%~dp0"
echo BabySitter setup for a copy of this folder.
echo This downloads the Python libraries named in requirements.txt.
echo It does not download Ollama, Python, or the models until you say yes to the models.
echo.

py -3.12 -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 is not installed.
  echo Install it from https://www.python.org/downloads/windows/
  echo On the first screen, check Add python.exe to PATH.
  echo Then double-click this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python folder .venv
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo The Python folder could not be created. Copy the text above.
    pause
    exit /b 1
  )
)

echo Installing the libraries. This can take a few minutes.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo The libraries did not install. Copy the text above.
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m babysitter.setupneed
echo.
set /p DOWNLOAD=Type Y to download qwen3.5:9b and gemma4:12b, or press Enter to skip: 
if /I "%DOWNLOAD%"=="Y" (
  ".venv\Scripts\python.exe" -m babysitter.setupneed --pull --yes
)
echo.
echo Double-click Run BabySitter.bat to open BabySitter.
pause
