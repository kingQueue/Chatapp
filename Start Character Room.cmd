@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0server.py" --open %*
  exit /b
)
where pythonw.exe >nul 2>nul
if %errorlevel% equ 0 (
  start "" pythonw.exe "%~dp0server.py" --open %*
  exit /b
)
python.exe "%~dp0server.py" --open %*
