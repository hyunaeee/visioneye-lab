@echo off
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0run.ps1" -PickVideo -Calibrate
if errorlevel 1 pause

