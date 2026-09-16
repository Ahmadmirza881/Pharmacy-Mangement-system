@echo off
title Mumtaz Pharmacy - Attendance & Payroll System
cd /d "%~dp0"

echo ========================================================
echo    MUMTAZ PHARMACY - ATTENDANCE & PAYROLL SYSTEM
echo ========================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python install nahi hai ya PATH me shamil nahi hai!
    echo Barah-e-karam https://www.python.org se Python install karein
    echo aur setup me "Add python.exe to PATH" ko lazmi tick karein.
    echo.
    pause
    exit /b
)

echo [1/3] Checking dependencies...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check

echo [2/3] Opening browser at http://localhost:8000 ...
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

echo [3/3] Server chal raha hai...
echo NOTE: Is window (black screen) ko band mat kijiyega jab tak system use ho raha ho.
echo Band karne k liye Ctrl + C press karein ya window close karein.
echo.
python main.py

pause
