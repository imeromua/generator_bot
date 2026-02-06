@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

cls
echo ╔════════════════════════════════════════╗
echo ║  Generator Bot - Запуск                ║
echo ╚════════════════════════════════════════╝
echo.

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "VENV_DIR=%ROOT%venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"
set "PIDFILE=%ROOT%bot.pid"
set "LOGDIR=%ROOT%logs"
set "ENV_FILE=%ROOT%.env"

REM ============================================
REM  АВТОМАТИЧНА ПІДГОТОВКА
REM ============================================

REM === 1. PYTHON ===
echo [1/8] Перевірка Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python не встановлено!
        echo.
        echo Завантажте Python 3.8+ з https://www.python.org/downloads/
        echo Встановіть з опцією "Add Python to PATH"
        pause
        exit /b 1
    )
    set "PYTHON_CMD=py -3"
) else (
    set "PYTHON_CMD=python"
)

for /f "delims=" %%v in ('!PYTHON_CMD! --version 2^>^&1') do set "PY_VERSION=%%v"
echo [OK] !PY_VERSION!

REM === 2. VENV ===
echo [2/8] Перевірка віртуального середовища...
if not exist "%VENV_PY%" (
    echo [INFO] venv не знайдено, створюю...
    !PYTHON_CMD! -m venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo [ERROR] Не вдалося створити venv!
        pause
        exit /b 1
    )
    echo [OK] venv створено
) else (
    echo [OK] venv існує
)

REM === 3. PIP ОНОВЛЕННЯ (НЕ КРИТИЧНЕ) ===
echo [3/8] Оновлення pip...
"%VENV_PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check 2>nul
if !errorlevel!==0 (
    echo [OK] pip оновлено
) else (
    echo [SKIP] Пропущено (не критично)
)

REM === 4. REQUIREMENTS.TXT ===
echo [4/8] Перевірка requirements.txt...
if not exist "%ROOT%requirements.txt" (
    echo [ERROR] requirements.txt не знайдено!
    pause
    exit /b 1
)
echo [OK] requirements.txt існує

REM === 5. ЗАЛЕЖНОСТІ ===
echo [5/8] Перевірка залежностей...
"%VENV_PY%" -c "import aiogram" >nul 2>&1
if !errorlevel! neq 0 (
    echo [INFO] Встановлюю залежності (це займе ~1 хвилину)...
    echo.
    "%VENV_PIP%" install -r "%ROOT%requirements.txt" --disable-pip-version-check
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Помилка встановлення залежностей!
        echo.
        echo Можливі причини:
        echo   - Немає інтернету
        echo   - PyPI недоступний
        echo   - Застарілий pip (спробуйте вручну: venv\Scripts\pip.exe install --upgrade pip)
        pause
        exit /b 1
    )
    echo [OK] Залежності встановлено
) else (
    REM Перевіряємо всі критичні пакети
    "%VENV_PY%" -c "import aiogram, gspread, openpyxl, pytz, dotenv" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [INFO] Оновлюю залежності...
        "%VENV_PIP%" install -r "%ROOT%requirements.txt" --quiet --disable-pip-version-check 2>nul
        if !errorlevel!==0 (
            echo [OK] Залежності оновлено
        ) else (
            echo [WARN] Не всі залежності встановлено, але продовжую...
        )
    ) else (
        echo [OK] Залежності актуальні
    )
)

REM === 6. .ENV ФАЙЛ ===
echo [6/8] Перевірка конфігурації...
if not exist "%ENV_FILE%" (
    echo [WARN] Файл .env не знайдено!
    echo [INFO] Створюю шаблон .env...
    
    (
        echo # --- КЛЮЧІ ---
        echo BOT_TOKEN=YOUR_BOT_TOKEN_HERE
        echo.
        echo # --- НАЛАШТУВАННЯ ТАБЛИЦІ ---
        echo SHEET_ID_PROD=YOUR_SHEET_ID_HERE
        echo SHEET_ID_TEST=YOUR_TEST_SHEET_ID_HERE
        echo SHEET_NAME=ЛЮТИЙ
        echo.
        echo # --- РЕЖИМ ---
        echo MODE=TEST
        echo.
        echo # --- ЧАС ТА МІСЦЕ ---
        echo TIMEZONE=Europe/Kyiv
        echo.
        echo # --- ГРАФІК РОБОТИ ---
        echo WORK_START=07:30
        echo WORK_END=20:30
        echo BRIEF_TIME=07:50
        echo.
        echo # --- ТЕХНІКА ---
        echo OIL_LIMIT=100
        echo.
        echo # --- ДОСТУП ---
        echo ADMINS=YOUR_TELEGRAM_ID_HERE
        echo BOT_STATUS=ON
        echo USERS=
        echo.
        echo # --- ПАЛИВО ---
        echo FUEL_RATE=5.3
    ) > "%ENV_FILE%"
    
    echo [OK] Створено .env шаблон
    echo.
    echo ════════════════════════════════════════
    echo  ⚠️  ВАЖЛИВО!
    echo ════════════════════════════════════════
    echo  Відредагуйте .env файл перед запуском:
    echo    - BOT_TOKEN (токен бота)
    echo    - SHEET_ID_PROD (ID Google Sheets)
    echo    - ADMINS (ваш Telegram ID)
    echo.
    echo  Після редагування запустіть start.bat знову
    echo ════════════════════════════════════════
    pause
    exit /b 0
)

REM Перевірка критичних параметрів
findstr /C:"BOT_TOKEN=YOUR_" "%ENV_FILE%" >nul
if !errorlevel!==0 (
    echo [ERROR] BOT_TOKEN не налаштовано!
    echo Відредагуйте .env файл
    pause
    exit /b 1
)

findstr /C:"ADMINS=YOUR_" "%ENV_FILE%" >nul
if !errorlevel!==0 (
    echo [ERROR] ADMINS не налаштовано!
    echo Відредагуйте .env файл
    pause
    exit /b 1
)

echo [OK] .env налаштовано

REM === 7. СТРУКТУРА ПРОЕКТУ ===
echo [7/8] Перевірка структури проекту...
set "STRUCT_OK=1"
if not exist "%ROOT%database\" (
    echo [ERROR] Директорія database\ не знайдена!
    set "STRUCT_OK=0"
)
if not exist "%ROOT%handlers\" (
    echo [ERROR] Директорія handlers\ не знайдена!
    set "STRUCT_OK=0"
)
if not exist "%ROOT%services\" (
    echo [ERROR] Директорія services\ не знайдена!
    set "STRUCT_OK=0"
)
if not exist "%ROOT%main.py" (
    echo [ERROR] Файл main.py не знайдений!
    set "STRUCT_OK=0"
)

if !STRUCT_OK!==0 (
    echo [ERROR] Неповна структура проекту!
    pause
    exit /b 1
)
echo [OK] Структура проекту OK

REM === 8. СТАТУС БОТА ===
echo [8/8] Перевірка чи бот вже запущений...
if exist "%PIDFILE%" (
    set /p OLD_PID=<"%PIDFILE%"
    powershell -NoProfile -Command "if (Get-Process -Id !OLD_PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
    if !errorlevel!==0 (
        echo [WARN] Бот вже запущений! PID=!OLD_PID!
        echo.
        echo Використайте:
        echo   stop.bat     - для зупинки
        echo   restart.bat  - для перезапуску
        pause
        exit /b 0
    ) else (
        del /q "%PIDFILE%" >nul 2>&1
    )
)
echo [OK] Бот не запущений

echo.
echo ════════════════════════════════════════
echo  📋 Підготовка завершена
echo ════════════════════════════════════════

REM ============================================
REM  СТВОРЕННЯ РОБОЧИХ ДИРЕКТОРІЙ
REM ============================================

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if not exist "%ROOT%backups" mkdir "%ROOT%backups"

REM ============================================
REM  РЕЗЕРВНА КОПІЯ БД
REM ============================================

if exist "%ROOT%generator.db" (
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
    copy /y "%ROOT%generator.db" "%ROOT%backups\generator_backup_!TS!.db" >nul 2>&1
    if !errorlevel!==0 (
        echo [INFO] Створено резервну копію БД
    )
    
    REM Видалення старих бекапів (залишаємо останні 10)
    for /f "skip=10 delims=" %%f in ('dir /b /o-d "%ROOT%backups\generator_backup_*.db" 2^>nul') do (
        del /q "%ROOT%backups\%%f" >nul 2>&1
    )
)

REM ============================================
REM  ЗАПУСК БОТА
REM ============================================

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "LOGFILE=%LOGDIR%\bot_!TS!.log"

echo.
echo ════════════════════════════════════════
echo  🚀 ЗАПУСК БОТА
echo ════════════════════════════════════════
echo  Лог: !LOGFILE!
echo ════════════════════════════════════════
echo.

REM Запуск через PowerShell з отриманням PID
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "$p = Start-Process -FilePath '%VENV_PY%' -ArgumentList @('-u','main.py') -WorkingDirectory '%ROOT%' -WindowStyle Hidden -PassThru -RedirectStandardOutput '!LOGFILE!' -RedirectStandardError '!LOGFILE!'; $p.Id"`) do set "PID=%%p"

if not defined PID (
    echo [ERROR] Не вдалося запустити бота!
    echo Перевірте логи: !LOGFILE!
    echo.
    pause
    exit /b 1
)

REM Збереження PID
echo !PID!>"%PIDFILE%"

REM Чекаємо 3 секунди та перевіряємо чи процес живий
echo [INFO] Перевірка запуску...
timeout /t 3 /nobreak >nul

powershell -NoProfile -Command "if (Get-Process -Id !PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if !errorlevel! neq 0 (
    echo [ERROR] Процес зупинився одразу після запуску!
    echo.
    echo Можливі причини:
    echo   - Помилка в коді
    echo   - Невірний токен бота
    echo   - Немає доступу до Telegram API
    echo.
    echo Перевірте логи: !LOGFILE!
    del /q "%PIDFILE%" >nul 2>&1
    echo.
    pause
    exit /b 1
)

echo.
echo ════════════════════════════════════════
echo  ✅ БОТ УСПІШНО ЗАПУЩЕНО!
echo ════════════════════════════════════════
echo.
echo  📊 Інформація:
echo    PID:  !PID!
echo    Лог:  !LOGFILE!
echo.
echo  💡 Корисні команди:
echo    stop.bat      - Зупинити бота
echo    restart.bat   - Перезапустити бота
echo    status.bat    - Перевірити статус
echo    logs.bat      - Переглянути логи
echo    check.bat     - Повна діагностика
echo.
echo ════════════════════════════════════════
echo.
echo Натисніть будь-яку клавішу для виходу...
pause >nul

exit /b 0
