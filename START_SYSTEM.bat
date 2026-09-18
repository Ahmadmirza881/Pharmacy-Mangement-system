@echo off
title Mumtaz Pharmacy - Attendance & Payroll System
cd /d "%~dp0"
color 0A

:: Detect local LAN IP
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address" /c:"IP Address"') do (
    set IP=%%a
    goto :found_ip
)
:found_ip
set IP=%IP: =%
if "%IP%"=="" set IP=127.0.0.1

cls
echo =====================================================================
echo           MUMTAZ PHARMACY SYSTEM - SERVER CHAL RAHA HAI
echo =====================================================================
echo.
echo  [1] Is Main PC (Server) par chalane k liye:
echo      http://localhost:8000
echo.
echo  [2] Dosre Counter PCs (LAN) par chalane k liye ye URL dalein:
echo      http://%IP%:8000
echo.
echo =====================================================================
echo  NOTE: Is black window ko band mat kijiyega jab tak kaam chal raha ho.
echo =====================================================================
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"
python main.py
pause
