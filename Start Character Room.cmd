@echo off
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if %errorlevel% equ 0 (
  start "" pythonw.exe "%~dp0server.py" --open
  exit /b
)
where python.exe >nul 2>nul
if %errorlevel% equ 0 (
  python.exe "%~dp0server.py" --open
  exit /b
)
echo Python 3.10 or newer is required to run Character Room.
echo Install Python from https://www.python.org/downloads/windows/ then try again.
pause
