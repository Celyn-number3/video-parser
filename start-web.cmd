@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-web.ps1" -OpenBrowser
set "exit_code=%errorlevel%"
if not "%exit_code%"=="0" (
    echo.
    echo Startup failed. Please check the error above.
    pause
)
exit /b %exit_code%
