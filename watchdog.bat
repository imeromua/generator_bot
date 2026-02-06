@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

cls
echo ╔════════════════════════════════════════╗
echo ║  Generator Bot - Watchdog              ║
echo ║  Автоматичний перезапуск при падінні   ║
echo ╚════════════════════════════════════════╝
echo.

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "VENV_PY=%ROOT%venv\Scripts\python.exe"
set "LOGDIR=%ROOT%logs"

set "CRASH_COUNT=0"
set "MAX_CRASHES=10"
set "CRASH_UPTIME_THRESHOLD=30"
set "RETRY_DELAY=10"
set "HARD_DELAY=120"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo ════════════════════════════════════════
echo  1) Підготовка (venv/requirements/.env/структура)
echo ════════════════════════════════════════
call "%ROOT%start.bat" --setup-only
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Setup step завершився помилкою. Дивись повідомлення вище.
    pause
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo.
    echo [ERROR] Не знайдено "%VENV_PY%"
    echo Переконайся що venv створився коректно.
    pause
    exit /b 1
)

echo.
echo ════════════════════════════════════════
echo  Watchdog запущено
echo ════════════════════════════════════════
echo  MAX_CRASHES: %MAX_CRASHES%
echo  UPTIME threshold: %CRASH_UPTIME_THRESHOLD%s
echo  RETRY_DELAY: %RETRY_DELAY%s
echo  Натисни Ctrl+C щоб зупинити watchdog
echo ════════════════════════════════════════
echo.

:LOOP
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
    set "LOGFILE=%LOGDIR%\watchdog_!TS!.log"

    echo [!TS!] Запуск main.py (лог: !LOGFILE!)...

    set "START_EPOCH="
    for /f "usebackq delims=" %%s in (`powershell -NoProfile -Command "[int][double]::Parse((Get-Date -UFormat %%s))"`) do set "START_EPOCH=%%s"

    "%VENV_PY%" -u main.py > "!LOGFILE!" 2>&1
    set "EXIT_CODE=!errorlevel!"

    set "END_EPOCH="
    for /f "usebackq delims=" %%e in (`powershell -NoProfile -Command "[int][double]::Parse((Get-Date -UFormat %%s))"`) do set "END_EPOCH=%%e"

    if not defined START_EPOCH set "START_EPOCH=0"
    if not defined END_EPOCH set "END_EPOCH=0"

    set /a "UPTIME_SEC=END_EPOCH-START_EPOCH"
    if !UPTIME_SEC! LSS 0 set "UPTIME_SEC=0"

    echo.
    echo ════════════════════════════════════════
    echo [!TS!] main.py завершився. ExitCode=!EXIT_CODE!, Uptime=!UPTIME_SEC!s
    echo ════════════════════════════════════════

    if !UPTIME_SEC! LSS %CRASH_UPTIME_THRESHOLD% (
        set /a CRASH_COUNT+=1
        echo [WARN] Швидке падіння: !CRASH_COUNT!/%MAX_CRASHES%

        if !CRASH_COUNT! GEQ %MAX_CRASHES% (
            echo.
            echo ════════════════════════════════════════
            echo [ERROR] Багато падінь підряд. Зупинка watchdog.
            echo Перевір:
            echo   - Доступ до api.telegram.org (VPN/Proxy/Firewall/ISP)
            echo   - Логи: !LOGFILE!
            echo ════════════════════════════════════════
            pause
            exit /b 1
        )

        echo [INFO] Очікування %RETRY_DELAY% секунд перед перезапуском...
        timeout /t %RETRY_DELAY% /nobreak >nul

        if !CRASH_COUNT! GEQ 5 (
            echo [INFO] Додаткова пауза %HARD_DELAY% секунд (щоб не "лупити" Telegram без кінця)...
            timeout /t %HARD_DELAY% /nobreak >nul
        )
    ) else (
        set "CRASH_COUNT=0"
        echo [OK] Uptime був достатній. Лічильник падінь скинуто.
        echo [INFO] Перезапуск через %RETRY_DELAY% секунд...
        timeout /t %RETRY_DELAY% /nobreak >nul
    )

    echo.
goto LOOP
