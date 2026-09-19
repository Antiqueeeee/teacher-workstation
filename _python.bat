@echo off
rem Resolve the bundled Python runtime; fall back to a system Python (dev machines only).
rem This file is called by the other scripts - teachers do not need to click it.
set "PY=%~dp0runtime\python.exe"
if exist "%PY%" exit /b 0
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Bundled Python runtime not found at runtime\python.exe,
  echo and there is no system Python either. Please unpack a complete copy.
  echo.
  pause
  exit /b 1
)
set "PY=python"
exit /b 0
