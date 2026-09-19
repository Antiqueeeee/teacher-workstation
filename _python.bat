@echo off
rem Resolve the bundled Python runtime. Teachers never install Python: the package
rem carries its own copy in runtime\ and we must NOT silently fall back to a Python
rem the teacher happens to have installed (that would depend on their environment).
rem Dev machines only: set TWS_ALLOW_SYSTEM_PYTHON=1 to allow the fallback.
rem This file is called by the other scripts - teachers do not need to click it.
set "PY=%~dp0runtime\python.exe"
if exist "%PY%" exit /b 0

if /i "%TWS_ALLOW_SYSTEM_PYTHON%"=="1" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo.
    echo TWS_ALLOW_SYSTEM_PYTHON=1 but there is no system Python either.
    echo.
    pause
    exit /b 1
  )
  set "PY=python"
  echo [dev] Using the system Python - this package should carry runtime\python.exe
  exit /b 0
)

echo.
echo Bundled Python runtime not found: runtime\python.exe
echo Please unpack a COMPLETE copy of this package (runtime\ must be next to the scripts).
echo Nothing has been installed on your computer, and nothing was changed.
echo.
pause
exit /b 1
