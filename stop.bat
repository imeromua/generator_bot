@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PIDFILE=%ROOT%bot.pid"

echo ╔════════════════════════════════════════╗
echo ║  Generator Bot - Stop                 ║
echo ╚════════════════════════════════════════╝
echo.

if not exist "%PIDFILE%" (
    echo [INFO] bot.pid не знайдено. Ймовірно бот не запущений через start.bat.
    exit /b 0
)

set /p PID=<"%PIDFILE%"
if not defined PID (
    echo [WARN] bot.pid порожній. Видаляю.
    del /q "%PIDFILE%" >nul 2>&1
    exit /b 0
)

powershell -NoProfile -Command "if (Get-Process -Id %PID% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Процес PID=%PID% не знайдений. Видаляю pidfile.
    del /q "%PIDFILE%" >nul 2>&1
    exit /b 0
)

echo [INFO] Зупиняю процес PID=%PID% ...
taskkill /PID %PID% /F >nul 2>&1

powershell -NoProfile -Command "Start-Sleep -Milliseconds 300; if (Get-Process -Id %PID% -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Не вдалося завершити процес PID=%PID% (можливо, потрібні права).
    exit /b 1
)

del /q "%PIDFILE%" >nul 2>&1
echo [OK] Бот зупинено, pidfile очищено.

exit /b 0
