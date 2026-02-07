import os
from dotenv import load_dotenv
import pytz
import sys

load_dotenv()

# --- ВАЛІДАЦІЯ КРИТИЧНИХ ПАРАМЕТРІВ ---
def validate_env():
    """Перевіряє наявність обов'язкових змінних"""
    required = ["BOT_TOKEN", "SHEET_ID_PROD", "SHEET_ID_TEST", "ADMINS"]
    missing = []

    for key in required:
        if not os.getenv(key):
            missing.append(key)

    if missing:
        print("=" * 60)
        print("❌ ПОМИЛКА КОНФІГУРАЦІЇ!")
        print("")
        print("Відсутні обов'язкові параметри в .env:")
        for key in missing:
            print(f"  - {key}")
        print("")
        print("Створіть .env файл з усіма необхідними параметрами.")
        print("=" * 60)
        sys.exit(1)

# Виконуємо валідацію
validate_env()

# --- КЛЮЧІ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- НАЛАШТУВАННЯ ТАБЛИЦІ ---
MODE = os.getenv("MODE", "TEST")
IS_TEST_MODE = (MODE == "TEST")

if IS_TEST_MODE:
    print("⚠️  УВАГА: Бот запущено в ТЕСТОВОМУ режимі (SHEET_ID_TEST)")
    SHEET_ID = os.getenv("SHEET_ID_TEST")
else:
    SHEET_ID = os.getenv("SHEET_ID_PROD")

SHEET_NAME = os.getenv("SHEET_NAME", "ЛЮТИЙ")

# --- ЧАС ТА МІСЦЕ ---
TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")
KYIV = pytz.timezone(TIMEZONE)

# --- ГРАФІК РОБОТИ ---
WORK_START_TIME = os.getenv("WORK_START", "07:30")
WORK_END_TIME = os.getenv("WORK_END", "20:30")
# ВАЖЛИВО: дефолт брифінгу = 07:30 (якщо BRIEF_TIME не задано в .env)
MORNING_BRIEF_TIME = os.getenv("BRIEF_TIME", "07:30")

# --- ТЕХНІКА ---
MAINTENANCE_LIMIT = int(os.getenv("OIL_LIMIT", "100"))

# --- ДОСТУП ---
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
BOT_STATUS = os.getenv("BOT_STATUS", "ON")
REGISTRATION_OPEN = (BOT_STATUS == "ON")
WHITELIST = [int(x.strip()) for x in os.getenv("USERS", "").split(",") if x.strip()]

# --- ПАЛИВО ---
FUEL_RATE_STR = os.getenv("FUEL_RATE")

if FUEL_RATE_STR:
    try:
        FUEL_CONSUMPTION = float(FUEL_RATE_STR)
    except ValueError:
        print(f"⚠️  УВАГА: FUEL_RATE='{FUEL_RATE_STR}' не є числом, використано 5.3 за замовчуванням")
        FUEL_CONSUMPTION = 5.3
else:
    print("⚠️  УВАГА: FUEL_RATE не вказано в .env, використано 5.3 л/год за замовчуванням")
    FUEL_CONSUMPTION = 5.3

# Пороги та анти-спам для алертів по паливу
try:
    FUEL_ALERT_THRESHOLD_L = float(os.getenv("FUEL_ALERT_THRESHOLD", "40"))
except Exception:
    FUEL_ALERT_THRESHOLD_L = 40.0

try:
    FUEL_ALERT_COOLDOWN_MIN = int(os.getenv("FUEL_ALERT_COOLDOWN_MIN", "60"))
except Exception:
    FUEL_ALERT_COOLDOWN_MIN = 60

# Нагадування "натисніть СТОП" за N хв до WORK_END_TIME
try:
    STOP_REMINDER_MIN_BEFORE_END = int(os.getenv("STOP_REMINDER_MIN", "15"))
except Exception:
    STOP_REMINDER_MIN_BEFORE_END = 15

# --- ІНФОРМАЦІЯ ПРО КОНФІГУРАЦІЮ ---
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("📋 ПОТОЧНА КОНФІГУРАЦІЯ")
    print("=" * 60)
    print(f"Режим: {'TEST' if IS_TEST_MODE else 'PROD'}")
    print(f"Таблиця: {SHEET_NAME}")
    print(f"ID таблиці: {SHEET_ID}")
    print(f"Адміни: {ADMIN_IDS}")
    print(f"Витрата палива: {FUEL_CONSUMPTION} л/год")
    print(f"Ліміт ТО: {MAINTENANCE_LIMIT} год")
    print(f"Поріг алерту палива: {FUEL_ALERT_THRESHOLD_L} л")
    print(f"Cooldown алерту: {FUEL_ALERT_COOLDOWN_MIN} хв")
    print(f"Нагадування СТОП: за {STOP_REMINDER_MIN_BEFORE_END} хв")
    print(f"Реєстрація: {'Відкрита' if REGISTRATION_OPEN else 'Закрита'}")
    print("=" * 60 + "\n")
