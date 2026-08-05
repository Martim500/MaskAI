@echo off
cd /d "%~dp0"
echo Stopping Masked Prompt Chat...
powershell -NoProfile -ExecutionPolicy Bypass -File "stop.ps1"
pause
