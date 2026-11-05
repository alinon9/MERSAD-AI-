@echo off
chcp 65001 >nul
cd /d "%~dp0"
call setup.bat || exit /b 1
venv\Scripts\python selftest.py
venv\Scripts\python check_install.py --camera
pause
