@echo off
rem Resolve the Python runtime. Teachers never install Python: this project carries its
rem own copy in runtime\ (created on first run by tools\bootstrap.py). We must NOT
rem silently use a Python the teacher happens to have installed.
rem This file is called by the other scripts - teachers do not need to click it.
set "PY=%~dp0runtime\python.exe"
if exist "%PY%" exit /b 0

rem First run: bootstrap the runtime using whatever system Python we can find.
rem The system Python is only used to DOWNLOAD and INSTALL into runtime\ ;
rem the service itself always runs on the bundled runtime.
set "BOOT=%~dp0tools\bootstrap.py"
if not exist "%BOOT" (
  echo tools\bootstrap.py is missing - please unpack a complete copy.
  pause
  exit /b 1
)
where python >nul 2>nul
if errorlevel 1 goto nopython
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" 2>nul
if errorlevel 1 goto nopython

echo.
echo First run: preparing the bundled Python runtime into runtime\ ...
echo Nothing will be installed into your own Python environment.
echo.
python "%~dp0tools\bootstrap.py"
if errorlevel 1 (
  pause
  exit /b 1
)
if exist "%PY%" exit /b 0
echo Bootstrap finished but runtime\python.exe is still missing.
pause
exit /b 1

:nopython
echo.
echo This project needs a Python runtime, and this computer does not have one yet.
echo Two ways to get it:
echo   1) Recommended: give this project's git address to an AI assistant (e.g. WorkBuddy)
echo      and ask it to run the project - it can prepare the runtime for you.
echo   2) Or install Python 3.11 from python.org once, then double-click the start script
echo      again: the project then sets up its own copy and your Python stays untouched.
echo Nothing has been installed or changed on your computer.
echo.
pause
exit /b 1
