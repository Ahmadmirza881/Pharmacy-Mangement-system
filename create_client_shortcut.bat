@echo off
title Mumtaz Pharmacy - Client Counter Shortcut Generator
color 0A

echo ================================================================
echo     MUMTAZ PHARMACY - CLIENT COUNTER SHORTCUT GENERATOR
echo ================================================================
echo.
echo Is PC ko Main Server PC se jorne k liye Server ka IP address likhein.
echo (Misal: 192.168.1.50 ya 192.168.1.100)
echo.

set /p SERVER_IP="Server PC ka IP likhein (Enter for default 192.168.1.50): "
if "%SERVER_IP%"=="" set SERVER_IP=192.168.1.50

echo.
echo [1/2] Connecting to Server at http://%SERVER_IP%:8000 ...
echo [2/2] Generating Desktop App Shortcut...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [System.Environment]::GetFolderPath('Desktop');" ^
  "$shortcutPath = Join-Path $desktop 'Mumtaz Pharmacy Counter.lnk';" ^
  "$wshell = New-Object -ComObject WScript.Shell;" ^
  "$shortcut = $wshell.CreateShortcut($shortcutPath);" ^
  "$edgePath = [System.IO.Path]::Combine($env:ProgramFiles, 'Microsoft\Edge\Application\msedge.exe');" ^
  "if (-not (Test-Path $edgePath)) { $edgePath = [System.IO.Path]::Combine(${env:ProgramFiles(x86)}, 'Microsoft\Edge\Application\msedge.exe'); }" ^
  "if (-not (Test-Path $edgePath)) { $edgePath = [System.IO.Path]::Combine($env:ProgramFiles, 'Google\Chrome\Application\chrome.exe'); }" ^
  "$shortcut.TargetPath = $edgePath;" ^
  "$shortcut.Arguments = '--app=http://%SERVER_IP%:8000';" ^
  "$shortcut.Description = 'Mumtaz Pharmacy Counter System';" ^
  "$shortcut.Save();" ^
  "Write-Host 'Desktop Shortcut Created Successfully at:' $shortcutPath -ForegroundColor Green"

echo.
echo ================================================================
echo [MUBARAK HO!] Desktop par 'Mumtaz Pharmacy Counter' ka icon ban gaya hai.
echo Is par double click karke software open karein.
echo ================================================================
echo.
pause
