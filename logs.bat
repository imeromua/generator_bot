@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "LOGDIR=%ROOT%logs"

echo ╔════════════════════════════════════════╗
echo ║  Generator Bot - Logs                 ║
echo ╚════════════════════════════════════════╝
echo.

if not exist "%LOGDIR%" (
    echo [INFO] Папка logs\ не знайдена.
    exit /b 0
)

set "LATEST_LOG="

for /f "usebackq delims=" %%f in (`powershell -NoProfile -Command "Get-ChildItem -Path '%LOGDIR%' -Filter '*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName"`) do set "LATEST_LOG=%%f"

if not defined LATEST_LOG (
    echo [INFO] Лог-файлів не знайдено у %LOGDIR%
    exit /b 0
)

echo [INFO] Останній лог:
echo %LATEST_LOG%
echo.
echo [INFO] Останні 200 рядків:
echo ------------------------------------------------------------
powershell -NoProfile -Command "Get-Content -Path '%LATEST_LOG%' -Tail 200"
echo ------------------------------------------------------------
echo.
pause
exit /b 0
