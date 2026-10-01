@echo off
setlocal
pushd "%~dp0"
if exist "data\first-run-accounts.json" (
  notepad "data\first-run-accounts.json"
) else (
  echo Run Start-Windows.cmd first to generate unique accounts.
  pause
)
popd
