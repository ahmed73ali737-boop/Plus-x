@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\launcher.py
  goto done
)
py -3.13 -c "import sys" >nul 2>nul
if not errorlevel 1 (
  py -3.13 tools\launcher.py
  goto done
)
python -c "import sys; assert sys.version_info[:2] in ((3,11),(3,12),(3,13))" >nul 2>nul
if not errorlevel 1 (
  python tools\launcher.py
  goto done
)
echo Python 3.13 is required. Install it from python.org, then retry.
start "" "START_WINDOWS_AR.html"
:done
popd
echo.
pause
