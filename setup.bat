@echo off
chcp 65001 >nul
setlocal EnableExtensions

cls
echo ╔════════════════════════════════════════╗
echo ║  Generator Bot - Налаштування          ║
echo ╚════════════════════════════════════════╝
echo.

set "ROOT=%~dp0"
cd /d "%ROOT%"

REM === ПЕРЕВІРКА PYTHON ===
echo [1/5] Перевірка Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python не встановлено!
        echo Завантажте з https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set "PYTHON_CMD=py -3"
) else (
    set "PYTHON_CMD=python"
)

for /f "delims=" %%v in ('%PYTHON_CMD% --version 2^>^&1') do set "PY_VERSION=%%v"
echo [OK] %PY_VERSION%

REM === СТВОРЕННЯ VENV ===
echo [2/5] Створення віртуального середовища...
if exist "venv" (
    echo [INFO] venv вже існує, пропускаю
) else (
    %PYTHON_CMD% -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Не вдалося створити venv!
        pause
        exit /b 1
    )
    echo [OK] venv створено
)

REM === ОНОВЛЕННЯ PIP ===
echo [3/5] Оновлення pip...
call "%ROOT%venv\Scripts\python.exe" -m pip install --upgrade pip -q
echo [OK] pip оновлено

REM === ВСТАНОВЛЕННЯ ЗАЛЕЖНОСТЕЙ ===
echo [4/5] Встановлення залежностей...
if not exist "requirements.txt" (
    echo [ERROR] requirements.txt не знайдено!
    pause
    exit /b 1
)
call "%ROOT%venv\Scripts\pip.exe" install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Помилка встановлення залежностей!
    pause
    exit /b 1
)
echo [OK] Залежності встановлено

REM === ПЕРЕВІРКА .ENV ===
echo [5/5] Перевірка конфігурації...
if not exist ".env" (
    echo [WARN] Файл .env не знайдено
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
    ) > .env
    
    echo [OK] Створено .env шаблон
    echo [WARN] ВАЖЛИВО: Відредагуйте .env перед запуском!
) else (
    echo [OK] .env існує
)

REM === СТВОРЕННЯ ДИРЕКТОРІЙ ===
if not exist "logs" mkdir "logs"
if not exist "backups" mkdir "backups"

echo.
echo ════════════════════════════════════════
echo  ✅ НАЛАШТУВАННЯ ЗАВЕРШЕНО!
echo ════════════════════════════════════════
echo.
echo  Наступні кроки:
echo    1. Відредагуйте .env файл
echo    2. Додайте service_account.json (для Google Sheets)
echo    3. Запустіть: start.bat
echo.
echo  Корисні команди:
echo    check.bat  - Діагностика
echo    start.bat  - Запустити бота
echo ════════════════════════════════════════
echo.

pause
exit /b 0
