@echo off
cd /d "%~dp0"
python.exe "%~dp0server.py" --stop
pause
