@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

cls
echo ╔════════════════════════════════════════╗
echo ║  Generator Bot - Діагностика           ║
echo ╚════════════════════════════════════════╝
echo.

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "VENV_PY=%ROOT%venv\Scripts\python.exe"
set "PIDFILE=%ROOT%bot.pid"
set "PASS=0"
set "FAIL=0"

REM === 1. Python ===
echo [1] Python...
where python >nul 2>&1 || where py >nul 2>&1
if %errorlevel%==0 (
    echo     ✅ Встановлено
    set /a PASS+=1
) else (
    echo     ❌ Не знайдено
    set /a FAIL+=1
)

REM === 2. venv ===
echo [2] Віртуальне середовище...
if exist "%VENV_PY%" (
    echo     ✅ Існує
    set /a PASS+=1
) else (
    echo     ❌ Не знайдено
    set /a FAIL+=1
)

REM === 3. Залежності ===
echo [3] Залежності...
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import aiogram, gspread, openpyxl, pytz" >nul 2>&1
    if !errorlevel!==0 (
        echo     ✅ Встановлено
        set /a PASS+=1
    ) else (
        echo     ❌ Не встановлено
        set /a FAIL+=1
    )
) else (
    echo     ⚠️  Пропущено (venv не існує)
)

REM === 4. .env ===
echo [4] Файл .env...
if exist "%ROOT%.env" (
    echo     ✅ Існує
    set /a PASS+=1
) else (
    echo     ❌ Не знайдено
    set /a FAIL+=1
)

REM === 5. service_account.json ===
echo [5] Файл service_account.json...
if exist "%ROOT%service_account.json" (
    echo     ✅ Існує
    set /a PASS+=1
) else (
    echo     ⚠️  Відсутній (Google Sheets не працюватиме)
)

REM === 6. База даних ===
echo [6] База даних...
if exist "%ROOT%generator.db" (
    for %%A in ("%ROOT%generator.db") do set "DBSIZE=%%~zA"
    echo     ✅ Існує (!DBSIZE! байт)
    set /a PASS+=1
) else (
    echo     ⚠️  Не знайдено (буде створена при старті)
)

REM === 7. Структура директорій ===
echo [7] Структура проекту...
set "STRUCTURE_OK=1"
if not exist "%ROOT%database\" set "STRUCTURE_OK=0"
if not exist "%ROOT%handlers\" set "STRUCTURE_OK=0"
if not exist "%ROOT%services\" set "STRUCTURE_OK=0"
if not exist "%ROOT%keyboards\" set "STRUCTURE_OK=0"
if not exist "%ROOT%middlewares\" set "STRUCTURE_OK=0"

if %STRUCTURE_OK%==1 (
    echo     ✅ OK
    set /a PASS+=1
) else (
    echo     ❌ Неповна
    set /a FAIL+=1
)

REM === 8. Статус бота ===
echo [8] Статус бота...
if exist "%PIDFILE%" (
    set /p PID=<"%PIDFILE%"
    powershell -NoProfile -Command "if (Get-Process -Id !PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
    if !errorlevel!==0 (
        echo     ✅ Запущено (PID=!PID!)
    ) else (
        echo     ⚠️  Застарілий PID файл
    )
) else (
    echo     ⚠️  Не запущено
)

REM === 9. Перевірка параметрів .env ===
echo [9] Параметри .env...
if exist "%ROOT%.env" (
    set "ENV_OK=1"
    findstr /C:"BOT_TOKEN=" "%ROOT%.env" >nul || set "ENV_OK=0"
    findstr /C:"SHEET_ID_PROD=" "%ROOT%.env" >nul || set "ENV_OK=0"
    findstr /C:"ADMINS=" "%ROOT%.env" >nul || set "ENV_OK=0"
    
    if !ENV_OK!==1 (
        echo     ✅ Критичні параметри присутні
        set /a PASS+=1
    ) else (
        echo     ❌ Відсутні критичні параметри
        set /a FAIL+=1
    )
) else (
    echo     ⚠️  Пропущено (.env не існує)
)

REM === 10. Доступ до диска ===
echo [10] Доступ до файлової системи...
echo test > "%ROOT%temp_test.tmp" 2>nul
if exist "%ROOT%temp_test.tmp" (
    del /q "%ROOT%temp_test.tmp" >nul 2>&1
    echo     ✅ Запис дозволено
    set /a PASS+=1
) else (
    echo     ❌ Немає прав на запис
    set /a FAIL+=1
)

echo.
echo ════════════════════════════════════════
echo  ПІДСУМОК
echo ════════════════════════════════════════
echo  ✅ Пройдено: !PASS!
echo  ❌ Помилок:  !FAIL!
echo ════════════════════════════════════════
echo.

if !FAIL! gtr 0 (
    echo [WARN] Виявлено проблеми!
    echo Рекомендації:
    if not exist "%VENV_PY%" echo   - Запустіть setup.bat
    if not exist "%ROOT%.env" echo   - Створіть .env файл
    echo.
)

pause
exit /b !FAIL!
