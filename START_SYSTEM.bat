@echo off
title Mumtaz Pharmacy - Attendance & Payroll System
cd /d "%~dp0"

echo ========================================================
echo    MUMTAZ PHARMACY - ATTENDANCE & PAYROLL SYSTEM
echo ========================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH!
    echo Please install Python from https://www.python.org
    echo and make sure to check "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b
)

echo [1/3] Checking dependencies...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check

echo [2/3] Opening browser at http://localhost:8000 ...
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

echo [3/3] Server is running...
echo NOTE: Please do not close this window while using the system.
echo To stop the server, press Ctrl + C or close this window.
echo.
python main.py

pause
