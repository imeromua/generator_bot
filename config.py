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

# --- PostgreSQL Connection Pool ---
try:
    PG_POOL_MIN_SIZE = int(os.getenv("PG_POOL_MIN_SIZE", "2"))
except ValueError:
    PG_POOL_MIN_SIZE = 2

try:
    PG_POOL_MAX_SIZE = int(os.getenv("PG_POOL_MAX_SIZE", "10"))
except ValueError:
    PG_POOL_MAX_SIZE = 10

try:
    PG_POOL_TIMEOUT = int(os.getenv("PG_POOL_TIMEOUT", "30"))
except ValueError:
    PG_POOL_TIMEOUT = 30

try:
    PG_POOL_MAX_IDLE = int(os.getenv("PG_POOL_MAX_IDLE", "300"))
except ValueError:
    PG_POOL_MAX_IDLE = 300

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
        print(f"Connection pool: min={PG_POOL_MIN_SIZE}, max={PG_POOL_MAX_SIZE}, timeout={PG_POOL_TIMEOUT}s, max_idle={PG_POOL_MAX_IDLE}s")
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


# --- MINI APP (Telegram WebApp) ---
WEBAPP_URL = (os.getenv("WEBAPP_URL", "") or "").strip()


# =====================================================================
# Pydantic-сумісні Settings-класи для структурованої конфігурації.
# Модуль-рівневі змінні (вище) залишаються основним API для бота.
# Ці класи використовуються в тестах та для валідації конфігурації.
# =====================================================================

from pathlib import Path as _Path


# Alias for backward compatibility (tests import env_bool)
env_bool = _env_bool


class DatabaseSettings:
    """Налаштування бази даних."""

    def __init__(self, *, backend="sqlite", sqlite_path=":memory:",
                 postgres_dsn=None, postgres_admin_dsn=None,
                 pg_pool_min_size=2, pg_pool_max_size=10,
                 pg_pool_timeout=30, pg_pool_max_idle=300):
        self.backend = backend
        self.sqlite_path = sqlite_path
        self.postgres_dsn = postgres_dsn
        self.postgres_admin_dsn = postgres_admin_dsn
        self.pg_pool_min_size = pg_pool_min_size
        self.pg_pool_max_size = pg_pool_max_size
        self.pg_pool_timeout = pg_pool_timeout
        self.pg_pool_max_idle = pg_pool_max_idle


class RedisSettings:
    """Налаштування Redis."""

    def __init__(self, *, enabled=False, url="redis://localhost:6379/0"):
        self.enabled = enabled
        self.url = url


class SheetsSettings:
    """Налаштування Google Sheets."""

    def __init__(self, *, sheet_id_prod=None, sheet_id_test=None,
                 service_account_path=None):
        self.sheet_id_prod = sheet_id_prod
        self.sheet_id_test = sheet_id_test
        self.service_account_path = _Path(service_account_path or "service_account.json")


class LoggingSettings:
    """Налаштування логування."""

    def __init__(self, *, log_level="ERROR", log_file="bot.log",
                 log_max_bytes=10 * 1024 * 1024, log_backup_count=5):
        self.log_level = log_level
        self.log_file = log_file
        self.log_max_bytes = log_max_bytes
        self.log_backup_count = log_backup_count


class WorkScheduleSettings:
    """Налаштування робочого графіка."""

    def __init__(self, *, timezone="Europe/Kyiv",
                 work_start_time="07:30", work_end_time="20:30",
                 morning_brief_time="07:30"):
        self.timezone = timezone
        self.work_start_time = work_start_time
        self.work_end_time = work_end_time
        self.morning_brief_time = morning_brief_time


class MaintenanceSettings:
    """Налаштування техобслуговування."""

    def __init__(self, *, oil_change_interval=100, spark_change_interval=100,
                 maintenance_interval=300, oil_limit=100):
        self.oil_change_interval = oil_change_interval
        self.spark_change_interval = spark_change_interval
        self.maintenance_interval = maintenance_interval
        self.oil_limit = oil_limit


class FuelSettings:
    """Налаштування палива."""

    def __init__(self, *, fuel_consumption=0.8, fuel_rate=None,
                 emergency_fuel_consumption=0.9,
                 fuel_alert_threshold=40.0):
        # fuel_rate -- аліас для fuel_consumption (зворотна сумісність)
        if fuel_rate is not None:
            self.fuel_consumption = fuel_rate
        else:
            self.fuel_consumption = fuel_consumption
        self.emergency_fuel_consumption = emergency_fuel_consumption
        self.fuel_alert_threshold = fuel_alert_threshold


class AccessSettings:
    """Налаштування доступу."""

    def __init__(self, *, admins=None, users=None, bot_status="ON"):
        self.admins = admins if admins is not None else os.getenv("ADMINS", "")
        self.users = users if users is not None else os.getenv("USERS", "")
        self.bot_status = bot_status

    def get_admin_ids(self):
        """Парсить рядок з ID адмінів у список int."""
        result = []
        for x in self.admins.split(","):
            x = x.strip()
            if x.isdigit():
                result.append(int(x))
        return result

    def get_whitelist(self):
        """Парсить рядок з ID користувачів у список int."""
        result = []
        for x in self.users.split(","):
            x = x.strip()
            if x.isdigit():
                result.append(int(x))
        return result

    @property
    def registration_open(self):
        return True


class Settings:
    """Головний клас конфігурації з підтримкою Pydantic-стилю.

    Використовує змінні оточення (os.environ) для ініціалізації.
    Підтримує вкладені об'єкти (database, logging, fuel, access тощо).
    """

    def __init__(self, *, bot_token=None, mode=None, database=None,
                 redis=None, sheets=None, logging_settings=None,
                 schedule=None, maintenance=None, fuel=None, access=None,
                 **kwargs):
        self.bot_token = bot_token or os.getenv("BOT_TOKEN", "")
        self.mode = mode or os.getenv("MODE", "TEST")

        # Вкладені об'єкти (dict → об'єкт, якщо передано dict)
        if isinstance(database, dict):
            self.database = DatabaseSettings(**database)
        else:
            self.database = database or DatabaseSettings(
                backend=os.getenv("DB_BACKEND", "sqlite") or "sqlite",
                sqlite_path=os.getenv("SQLITE_PATH", ":memory:") or ":memory:",
                postgres_dsn=os.getenv("POSTGRES_DSN") or None,
            )

        if isinstance(redis, dict):
            self.redis = RedisSettings(**redis)
        else:
            self.redis = redis or RedisSettings(
                enabled=_env_bool("REDIS_ENABLED", False),
                url=os.getenv("REDIS_URL", "redis://localhost:6379/0") or "redis://localhost:6379/0",
            )

        if isinstance(sheets, dict):
            self.sheets = SheetsSettings(**sheets)
        else:
            self.sheets = sheets or SheetsSettings(
                sheet_id_prod=os.getenv("SHEET_ID_PROD"),
                sheet_id_test=os.getenv("SHEET_ID_TEST"),
            )

        if isinstance(logging_settings, dict):
            self.logging = LoggingSettings(**logging_settings)
        else:
            self.logging = logging_settings or LoggingSettings(
                log_level=os.getenv("LOG_LEVEL", "ERROR"),
            )

        if isinstance(schedule, dict):
            self.schedule = WorkScheduleSettings(**schedule)
        else:
            self.schedule = schedule or WorkScheduleSettings()

        if isinstance(maintenance, dict):
            self.maintenance = MaintenanceSettings(**maintenance)
        else:
            self.maintenance = maintenance or MaintenanceSettings()

        if isinstance(fuel, dict):
            self.fuel = FuelSettings(**fuel)
        else:
            fuel_rate_env = os.getenv("FUEL_CONSUMPTION") or os.getenv("FUEL_RATE")
            fuel_val = float(fuel_rate_env) if fuel_rate_env else 0.8
            emerg_env = os.getenv("EMERGENCY_FUEL_CONSUMPTION")
            emerg_val = float(emerg_env) if emerg_env else 0.9
            self.fuel = fuel or FuelSettings(
                fuel_consumption=fuel_val,
                emergency_fuel_consumption=emerg_val,
            )

        if isinstance(access, dict):
            self.access = AccessSettings(**access)
        else:
            self.access = access or AccessSettings(
                admins=os.getenv("ADMINS", ""),
                users=os.getenv("USERS", ""),
                bot_status=os.getenv("BOT_STATUS", "ON"),
            )

    @property
    def is_test_mode(self):
        return self.mode == "TEST"

    @property
    def sheet_id(self):
        if self.is_test_mode:
            return os.getenv("SHEET_ID_TEST", self.sheets.sheet_id_test)
        return os.getenv("SHEET_ID_PROD", self.sheets.sheet_id_prod)

    @property
    def kyiv_tz(self):
        try:
            return ZoneInfo(self.schedule.timezone)
        except Exception:
            return ZoneInfo("Europe/Kyiv")

    def print_config(self):
        """Виводить поточну конфігурацію."""
        print(f"Configuration: mode={self.mode}, db={self.database.backend}")

    # --- Зворотна сумісність: UPPERCASE аліаси ---
    @property
    def BOT_TOKEN(self):
        return self.bot_token

    @property
    def MODE(self):
        return self.mode

    @property
    def IS_TEST_MODE(self):
        return self.is_test_mode

    @property
    def DB_BACKEND(self):
        return self.database.backend

    @property
    def SQLITE_PATH(self):
        return self.database.sqlite_path

    @property
    def FUEL_CONSUMPTION(self):
        return self.fuel.fuel_consumption

    @property
    def ADMIN_IDS(self):
        return self.access.get_admin_ids()

    @property
    def KYIV(self):
        return self.kyiv_tz
