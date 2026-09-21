@echo off
title Mumtaz Pharmacy Counter
start chrome.exe --app=http://192.168.100.88:8000
if %errorlevel% neq 0 (
    start "" "http://192.168.100.88:8000"
)
exit
