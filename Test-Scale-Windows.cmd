@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run Start-Windows.cmd once to create the environment.
  exit /b 1
)
.venv\Scripts\python.exe tests\load_profiles.py --profile x5
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\python.exe tests\load_profiles.py --profile x10
exit /b %errorlevel%
