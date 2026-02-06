@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ╔════════════════════════════════════════╗
echo ║  Generator Bot - Restart              ║
echo ╚════════════════════════════════════════╝
echo.

call "%ROOT%stop.bat"
echo.
echo [INFO] Пауза 2 секунди...
timeout /t 2 /nobreak >nul
echo.

call "%ROOT%start.bat"
exit /b %errorlevel%
