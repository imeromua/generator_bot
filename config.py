import os
import sys
import pytz
from dotenv import load_dotenv

load_dotenv()

def get_list(key):
    val = os.getenv(key, "")
    return [int(x.strip()) for x in val.split(",") if x.strip().isdigit()]

def get_bool(key):
    return os.getenv(key, "OFF").upper() in ["ON", "TRUE"]

BOT_TOKEN = os.getenv("BOT_TOKEN")
IS_TEST_MODE = os.getenv("MODE", "PROD").upper() == "TEST"

if IS_TEST_MODE:
    SHEET_ID = os.getenv("SHEET_ID_TEST")
    print("⚠️  УВАГА: Бот запущено в ТЕСТОВОМУ режимі (SHEET_ID_TEST)")
else:
    SHEET_ID = os.getenv("SHEET_ID_PROD")
    print("✅  Бот запущено в РОБОЧОМУ режимі (SHEET_ID_PROD)")

if not SHEET_ID:
    print("❌ ПОМИЛКА: Не знайдено SHEET_ID в .env!")
    sys.exit(1)

SHEET_NAME = os.getenv("SHEET_NAME", "ЛЮТИЙ")

ADMIN_IDS = get_list("ADMINS")
WHITELIST_IDS = get_list("USERS")
REGISTRATION_OPEN = get_bool("BOT_STATUS")

TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")
KYIV = pytz.timezone(TIMEZONE)

WORK_START_TIME = os.getenv("WORK_START", "07:30")
WORK_END_TIME = os.getenv("WORK_END", "20:30")
MORNING_BRIEF_TIME = os.getenv("BRIEF_TIME", "07:50")

MAINTENANCE_LIMIT = int(os.getenv("OIL_LIMIT", "100"))
# 👇 НОВЕ: Витрата палива
FUEL_CONSUMPTION = float(os.getenv("FUEL_RATE", "1.5"))

REMINDER_DELAY = 15