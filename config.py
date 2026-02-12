import os
import sys
from zoneinfo import ZoneInfo

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
        # Додаткова перевірка наявності psycopg при використанні Postgres
        try:
            import psycopg  # type: ignore
        except Exception:
            print("=" * 60)
            print("❌ ПОМИЛКА КОНФІГУРАЦІЇ!")
            print("")
            print("DB_BACKEND=postgres, але модуль 'psycopg' не встановлено.")
            print("Встановіть psycopg (наприклад, 'pip install psycopg[binary]') або змініть DB_BACKEND.")
            print("=" * 60)
            sys.exit(1)

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
POSTGRES_ADMIN_DSN = (os.getenv("POSTGRES_ADMIN_DSN", "") or "").strip()

# --- REDIS ---
REDIS_ENABLED = _env_bool("REDIS_ENABLED", False)
REDIS_URL = (os.getenv("REDIS_URL", "redis://localhost:6379/0") or "").strip()

# --- Google Sheets runtime integration ---
# If False: bot works DB-only at runtime; import/export can be kept manual.
SHEETS_RUNTIME_ENABLED = _env_bool("SHEETS_RUNTIME_ENABLED", True)

# FIX #26: Configurable service account path for Google Sheets authentication
SERVICE_ACCOUNT_PATH = (os.getenv("SERVICE_ACCOUNT_PATH", "service_account.json") or "service_account.json").strip()

# --- ЛОГУВАННЯ ---
LOG_FILE = os.getenv("LOG_FILE", "bot.log")
try:
    LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", 10485760))
except ValueError:
    LOG_MAX_BYTES = 10485760

try:
    LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", 5))
except ValueError:
    LOG_BACKUP_COUNT = 5

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


# --- НАЛАШТУВАННЯ ТАБЛИЦІ ---
MODE = os.getenv("MODE", "TEST")
IS_TEST_MODE = (MODE == "TEST")

if IS_TEST_MODE:
    print("⚠️  УВАГА: Бот запущено в ТЕСТОВОМУ режимі (SHEET_ID_TEST)")
    SHEET_ID = os.getenv("SHEET_ID_TEST")
else:
    SHEET_ID = os.getenv("SHEET_ID_PROD")

SHEET_NAME = os.getenv("SHEET_NAME", "ЛЮТИЙ")
LOGS_SHEET_NAME = os.getenv("LOGS_SHEET_NAME", "ПОДІЇ")

# --- ЧАС ТА МІСЦЕ ---
TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")
try:
    KYIV = ZoneInfo(TIMEZONE)
except Exception:
    print(f"⚠️ Невідома таймзона {TIMEZONE}, використовується UTC")
    KYIV = ZoneInfo("UTC")

# --- ГРАФІК РОБОТИ ---
WORK_START_TIME = os.getenv("WORK_START", "07:30")
WORK_END_TIME = os.getenv("WORK_END", "20:30")
MORNING_BRIEF_TIME = os.getenv("BRIEF_TIME", "07:30")

# --- ТЕХНІЧНЕ ОБСЛУГОВУВАННЯ (ТО) ---
# Інтервали ТО в мотогодинах (однакові для обох генераторів)
try:
    OIL_CHANGE_INTERVAL = int(os.getenv("OIL_CHANGE_INTERVAL", "100"))
except ValueError:
    OIL_CHANGE_INTERVAL = 100

try:
    SPARK_CHANGE_INTERVAL = int(os.getenv("SPARK_CHANGE_INTERVAL", "100"))
except ValueError:
    SPARK_CHANGE_INTERVAL = 100

try:
    MAINTENANCE_INTERVAL = int(os.getenv("MAINTENANCE_INTERVAL", "300"))
except ValueError:
    MAINTENANCE_INTERVAL = 300

# Зворотна сумісність з старим OIL_LIMIT
MAINTENANCE_LIMIT = int(os.getenv("OIL_LIMIT", str(OIL_CHANGE_INTERVAL)))

# --- ДОСТУП ---
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
BOT_STATUS = os.getenv("BOT_STATUS", "ON")
REGISTRATION_OPEN = (BOT_STATUS == "ON")
WHITELIST = [int(x.strip()) for x in os.getenv("USERS", "").split(",") if x.strip()]

# --- ПАЛИВО (ОСНОВНИЙ ГЕНЕРАТОР) ---
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

# --- ПАЛИВО (АВАРІЙНИЙ ГЕНЕРАТОР) ---
# Якщо не вказано - використовує FUEL_CONSUMPTION як дефолт
EMERGENCY_FUEL_STR = os.getenv("EMERGENCY_FUEL_CONSUMPTION")

if EMERGENCY_FUEL_STR:
    try:
        EMERGENCY_FUEL_CONSUMPTION = float(EMERGENCY_FUEL_STR)
    except ValueError:
        print(
            f"⚠️  УВАГА: EMERGENCY_FUEL_CONSUMPTION='{EMERGENCY_FUEL_STR}' не є числом, "
            f"використано {FUEL_CONSUMPTION} л/год (як для основного)"
        )
        EMERGENCY_FUEL_CONSUMPTION = FUEL_CONSUMPTION
else:
    # Якщо не вказано - використовуємо таку ж витрату як у основного
    EMERGENCY_FUEL_CONSUMPTION = FUEL_CONSUMPTION

# --- СПОВІЩЕННЯ ПРО ПАЛИВО ---
try:
    FUEL_ALERT_THRESHOLD_L = float(os.getenv("FUEL_ALERT_THRESHOLD", "40"))
except Exception:
    FUEL_ALERT_THRESHOLD_L = 40.0

try:
    FUEL_ALERT_COOLDOWN_MIN = int(os.getenv("FUEL_ALERT_COOLDOWN_MIN", "60"))
except Exception:
    FUEL_ALERT_COOLDOWN_MIN = 60

try:
    STOP_REMINDER_MIN_BEFORE_END = int(os.getenv("STOP_REMINDER_MIN", "15"))
except Exception:
    STOP_REMINDER_MIN_BEFORE_END = 15

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("📋 ПОТОЧНА КОНФІГУРАЦІЯ")
    print("=" * 60)
    print(f"Режим: {'TEST' if IS_TEST_MODE else 'PROD'}")
    print(f"Log Level: {LOG_LEVEL}")
    print(f"Log File: {LOG_FILE} (Max: {LOG_MAX_BYTES/1024/1024:.1f} MB, Backups: {LOG_BACKUP_COUNT})")
    print(f"DB backend: {DB_BACKEND}")
    if DB_BACKEND == "sqlite":
        print(f"SQLite path: {SQLITE_PATH}")
    if DB_BACKEND == "postgres":
        print(f"Postgres DSN: {'(set)' if bool(POSTGRES_DSN) else '(missing)'}")
    print(f"Redis enabled: {REDIS_ENABLED}")
    print(f"Sheets runtime enabled: {SHEETS_RUNTIME_ENABLED}")
    print(f"Service account path: {SERVICE_ACCOUNT_PATH}")
    print(f"Таблиця: {SHEET_NAME}")
    print(f"ID таблиці: {SHEET_ID}")
    print(f"Вкладка логів: {LOGS_SHEET_NAME}")
    print(f"Адміни: {ADMIN_IDS}")
    print(f"Витрата палива (основний): {FUEL_CONSUMPTION} л/год")
    print(f"Витрата палива (аварійний): {EMERGENCY_FUEL_CONSUMPTION} л/год")
    print(f"Інтервали ТО:")
    print(f"  Мастило: {OIL_CHANGE_INTERVAL} год")
    print(f"  Свічки: {SPARK_CHANGE_INTERVAL} год")
    print(f"  Планове ТО: {MAINTENANCE_INTERVAL} год")
    print(f"Таймзона: {KYIV}")
    print("=" * 60 + "\n")
