@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
set "PYTHONUTF8=1"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
%PY% -c "import pytest,httpx,coverage,psutil" >nul 2>nul
if errorlevel 1 (
  echo QA dependencies are missing.
  echo Run: %PY% -m pip install -r requirements-qa.txt
  goto done
)
%PY% -m pytest -q || goto fail
%PY% tests\native_acceptance.py || goto fail
%PY% tests\security_hardening.py || goto fail
%PY% tests\ux_contract_w08.py || goto fail
%PY% tests\capacity_smoke.py || goto fail
%PY% tests\sdk_native_smoke.py || goto fail
node --check sdk\javascript\index.mjs >nul 2>nul
if errorlevel 1 goto fail
node tests\sdk_js_test.mjs || goto fail
echo.
echo All available Windows hardening checks completed. Review QA_REPORT_AR.md for what these checks do NOT prove.
goto done
:fail
echo.
echo One or more checks failed. Do not treat the build as accepted.
:done
popd
pause
