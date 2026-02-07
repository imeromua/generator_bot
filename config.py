import os
import sys

import pytz
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


# --- ВАЛІДАЦІЯ КРИТИЧНИХ ПАРАМЕТРІВ ---
def validate_env():
    """Перевіряє наявність обов'язкових змінних.

    Важливо: НЕ викликається автоматично при імпорті config.
    Викликайте з точки входу (main.py) перед запуском бота.
    """

    required = ["BOT_TOKEN", "SHEET_ID_PROD", "SHEET_ID_TEST", "ADMINS"]

    db_backend = (os.getenv("DB_BACKEND", "sqlite") or "sqlite").strip().lower()
    if db_backend == "postgres":
        required.append("POSTGRES_DSN")

    if _env_bool("REDIS_ENABLED", False):
        required.append("REDIS_URL")

    missing = [key for key in required if not os.getenv(key)]

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


# --- КЛЮЧІ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- DB BACKEND ---
DB_BACKEND = (os.getenv("DB_BACKEND", "sqlite") or "sqlite").strip().lower()
SQLITE_PATH = (os.getenv("SQLITE_PATH", "generator.db") or "generator.db").strip()
POSTGRES_DSN = (os.getenv("POSTGRES_DSN", "") or "").strip()
# Admin DSN потрібен для автосоздання БД (CREATE DATABASE) якщо її ще немає.
# Якщо не задано, бот спробує створити БД через звичайний DSN (може не мати прав).
POSTGRES_ADMIN_DSN = (os.getenv("POSTGRES_ADMIN_DSN", "") or "").strip()

# --- REDIS ---
REDIS_ENABLED = _env_bool("REDIS_ENABLED", False)
REDIS_URL = (os.getenv("REDIS_URL", "redis://localhost:6379/0") or "").strip()

# --- НАЛАШТУВАННЯ ТАБЛИЦІ ---
MODE = os.getenv("MODE", "TEST")
IS_TEST_MODE = (MODE == "TEST")

if IS_TEST_MODE:
    print("⚠️  УВАГА: Бот запущено в ТЕСТОВОМУ режимі (SHEET_ID_TEST)")
    SHEET_ID = os.getenv("SHEET_ID_TEST")
else:
    SHEET_ID = os.getenv("SHEET_ID_PROD")

SHEET_NAME = os.getenv("SHEET_NAME", "ЛЮТИЙ")

# Окрема вкладка для журналу подій (крок 4)
LOGS_SHEET_NAME = os.getenv("LOGS_SHEET_NAME", "ПОДІЇ")

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
# Підтримуємо обидві назви для сумісності:
# - FUEL_RATE (основна)
# - FUEL_CONSUMPTION (аліас)
FUEL_RATE_STR = os.getenv("FUEL_RATE") or os.getenv("FUEL_CONSUMPTION")

if FUEL_RATE_STR:
    try:
        FUEL_CONSUMPTION = float(FUEL_RATE_STR)
    except ValueError:
        print(
            f"⚠️  УВАГА: FUEL_RATE/FUEL_CONSUMPTION='{FUEL_RATE_STR}' не є числом, використано 5.3 за замовчуванням"
        )
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
    print(f"DB backend: {DB_BACKEND}")
    if DB_BACKEND == "sqlite":
        print(f"SQLite path: {SQLITE_PATH}")
    if DB_BACKEND == "postgres":
        print(f"Postgres DSN: {'(set)' if bool(POSTGRES_DSN) else '(missing)'}")
        print(f"Postgres admin DSN: {'(set)' if bool(POSTGRES_ADMIN_DSN) else '(missing)'}")
    print(f"Redis enabled: {REDIS_ENABLED}")
    print(f"Таблиця: {SHEET_NAME}")
    print(f"ID таблиці: {SHEET_ID}")
    print(f"Вкладка логів: {LOGS_SHEET_NAME}")
    print(f"Адміни: {ADMIN_IDS}")
    print(f"Витрата палива: {FUEL_CONSUMPTION} л/год")
    print(f"Ліміт ТО: {MAINTENANCE_LIMIT} год")
    print(f"Поріг алерту палива: {FUEL_ALERT_THRESHOLD_L} л")
    print(f"Cooldown алерту: {FUEL_ALERT_COOLDOWN_MIN} хв")
    print(f"Нагадування СТОП: за {STOP_REMINDER_MIN_BEFORE_END} хв")
    print(f"Реєстрація: {'Відкрита' if REGISTRATION_OPEN else 'Закрита'}")
    print("=" * 60 + "\n")
