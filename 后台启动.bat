@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
title Teacher Workstation
call "%~dp0_python.bat" || exit /b 1
"%PY%" "%~dp0launcher.py" --daemon
pause
