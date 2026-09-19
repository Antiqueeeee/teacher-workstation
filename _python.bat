@echo off
rem Resolve the Python runtime. Teachers never install Python: this project carries its
rem own copy in runtime\ (prepared on first run by tools\bootstrap.py). We must NOT
rem silently use a Python the teacher happens to have installed.
rem This file is called by the other scripts - teachers do not need to click it.
rem
rem Written with labels instead of ( ) blocks on purpose: a ")" inside an echo line
rem inside a block closes the block early and cmd reports "was unexpected at this time".
set "PY=%~dp0runtime\python.exe"
set "BOOT=%~dp0tools\bootstrap.py"
if not exist "%BOOT%" goto noboot
if not exist "%PY%" goto bootstrap

rem Runtime present: make sure its dependencies are really there. Just checking that
rem the file exists is not enough - an install interrupted halfway (network drop,
rem window closed) leaves a runtime that imports nothing, and the service then dies
rem with a raw ModuleNotFoundError. --check is offline and takes about a second.
"%PY%" "%BOOT%" --check >nul 2>nul
if not errorlevel 1 exit /b 0
echo.
echo The bundled runtime exists but its dependencies are incomplete - repairing.

:bootstrap
rem Something to run the bootstrap with: a system Python 3.9+, or failing that the
rem bundled runtime itself (it only needs the standard library to do this).
set "DRIVER="
where python >nul 2>nul
if errorlevel 1 goto tryruntime
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if errorlevel 1 goto tryruntime
set "DRIVER=python"
goto runbootstrap

:tryruntime
if exist "%PY%" set "DRIVER=%PY%"
if not defined DRIVER goto nopython

:runbootstrap
echo.
echo Preparing the bundled Python runtime into runtime\ ...
echo Nothing will be installed into your own Python environment.
echo.
"%DRIVER%" "%BOOT%"
if errorlevel 1 goto bootfail
if not exist "%PY%" goto missingafter
exit /b 0

:noboot
echo tools\bootstrap.py is missing - please unpack a complete copy.
pause
exit /b 1

:nopython
echo.
echo This project needs a Python runtime, and this computer does not have one yet.
echo Two ways to get it:
echo    1^) Recommended: give this project's git address to an AI assistant ^(like WorkBuddy^)
echo       and ask it to run the project - it can prepare the runtime for you.
echo    2^) Or install Python 3.11 from python.org once, then double-click the start script
echo       again: the project sets up its own copy, and your Python stays untouched.
echo Nothing has been installed or changed on your computer.
echo.
pause
exit /b 1

:bootfail
pause
exit /b 1

:missingafter
echo Bootstrap finished but runtime\python.exe is still missing.
pause
exit /b 1
