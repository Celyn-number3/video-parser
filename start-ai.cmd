@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-ai.ps1"
set "exit_code=%errorlevel%"
if not "%exit_code%"=="0" (
    echo.
    echo Local AI startup failed. Check the error above.
    pause
)
exit /b %exit_code%
