@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PIDFILE=%ROOT%bot.pid"

echo ╔════════════════════════════════════════╗
echo ║  Generator Bot - Status               ║
echo ╚════════════════════════════════════════╝
echo.

if not exist "%PIDFILE%" (
    echo [INFO] bot.pid не знайдено. Бот не запущений через start.bat (або pidfile видалено).
    exit /b 0
)

set /p PID=<"%PIDFILE%"
if not defined PID (
    echo [WARN] bot.pid порожній.
    exit /b 1
)

powershell -NoProfile -Command "if (Get-Process -Id %PID% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] PID=%PID% не активний. Можливо бот впав. (pidfile існує)
    exit /b 1
)

echo [OK] Бот працює. PID=%PID%
exit /b 0
