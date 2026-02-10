"""Модуль імпорту з Google Sheets в БД.

Читає дані з основної вкладки (A-AC) і вкладки LOGS_SHEET_NAME.
Відновлює logs, maintenance, drivers, personnel в БД.

Важливо:
- Витрата палива береться з ENV через config.FUEL_CONSUMPTION.
- Назва вкладки логів береться з ENV через config.LOGS_SHEET_NAME.
"""

import logging
from datetime import datetime

import config
from database.models import get_connection
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


def _fuel_rate() -> float:
    """Єдине джерело правди для витрати палива (л/год)"""
    try:
        return float(getattr(config, "FUEL_CONSUMPTION", 0.0) or 0.0)
    except Exception:
        return 0.0


def _logs_sheet_name() -> str:
    return (getattr(config, "LOGS_SHEET_NAME", None) or "ПОДІЇ").strip() or "ПОДІЇ"


def _parse_date(date_str: str) -> str | None:
    """Парсить DD.MM.YYYY в YYYY-MM-DD"""
    if not date_str or not date_str.strip():
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%d.%m.%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_time(time_str: str) -> str | None:
    """Парсить HH:MM в HH:MM:00"""
    if not time_str or not time_str.strip():
        return None
    try:
        parts = time_str.strip().split(":")
        if len(parts) == 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
        return None
    except Exception:
        return None


def _clear_db():
    """Очищає БД перед імпортом"""
    logger.info("🧹 Очищаємо БД перед імпортом...")
    with get_connection() as conn:
        conn.execute("DELETE FROM logs")
        conn.execute("DELETE FROM schedule")
        conn.execute("DELETE FROM maintenance")
        conn.execute("DELETE FROM drivers")
        conn.execute("DELETE FROM personnel_names")
        conn.execute("DELETE FROM user_personnel")
        conn.commit()
    logger.info("✅ БД очищено")


def _restore_generator_state():
    """Відновлює generator_state з логів."""
    logger.info("🔧 Відновлюємо стан генератора з логів...")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT event_type, timestamp, value
        FROM logs
        ORDER BY timestamp ASC
    """
    )
    rows = cur.fetchall()

    cur.execute(
        """
        SELECT date, type, hours
        FROM maintenance
        ORDER BY date DESC
        LIMIT 10
    """
    )
    mnt_rows = cur.fetchall()

    rate = _fuel_rate()

    running_fuel = 0.0
    running_hours = 0.0
    active_shifts = {}  # {shift: start_time}

    for event, ts_str, value in rows:
        if event == "refill":
            running_fuel += float(value or 0)
        elif event == "fuel_set":
            running_fuel = float(value or 0)
        elif event.endswith("_start"):
            shift = event.split("_")[0]
            active_shifts[shift] = ts_str
        elif event.endswith("_end"):
            shift = event.split("_")[0]
            if shift in active_shifts:
                try:
                    start_ts = datetime.strptime(active_shifts[shift], "%Y-%m-%d %H:%M:%S")
                    end_ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    delta = (end_ts - start_ts).total_seconds() / 3600.0
                    running_hours += delta
                    running_fuel -= delta * rate
                except Exception:
                    pass
                del active_shifts[shift]
        elif event == "total_hours_set":
            running_hours = float(value or 0)

    last_oil = ""
    last_spark = ""

    for date_str, mnt_type, hours in mnt_rows:
        if mnt_type == "oil" and not last_oil:
            last_oil = date_str
        elif mnt_type == "spark" and not last_spark:
            last_spark = date_str

        if last_oil and last_spark:
            break

    conn.execute("UPDATE generator_state SET value = ? WHERE key = 'current_fuel'", (str(running_fuel),))
    conn.execute("UPDATE generator_state SET value = ? WHERE key = 'total_hours'", (str(running_hours),))

    if last_oil:
        conn.execute("UPDATE generator_state SET value = ? WHERE key = 'last_oil_change'", (last_oil,))
    if last_spark:
        conn.execute("UPDATE generator_state SET value = ? WHERE key = 'last_spark_change'", (last_spark,))

    conn.execute("UPDATE generator_state SET value = 'OFF' WHERE key = 'status'")
    conn.execute("UPDATE generator_state SET value = 'none' WHERE key = 'active_shift'")

    conn.commit()
    conn.close()

    logger.info(f"✅ Стан відновлено: паливо={running_fuel:.1f}л, мотогодини={running_hours:.1f}")


def _import_main_sheet_data(data_rows):
    """Імпорт даних, які вже зчитані з таблиці (без мережевих запитів)."""
    conn = get_connection()

    all_drivers = set()
    all_personnel = set()

    for row_idx, row in enumerate(data_rows, start=3):
        if len(row) < 29:
            row.extend([""] * (29 - len(row)))

        date_str = _parse_date(row[0])
        if not date_str:
            continue

        shifts = [
            ("m", row[1], row[2]),
            ("d", row[3], row[4]),
            ("e", row[5], row[6]),
            ("x", row[7], row[8]),
        ]

        shift_users = [
            (row[18], row[19]),
            (row[20], row[21]),
            (row[22], row[23]),
            (row[24], row[25]),
        ]

        for i, (shift_code, start_time, end_time) in enumerate(shifts):
            start_user, end_user = shift_users[i]

            start_parsed = _parse_time(start_time)
            end_parsed = _parse_time(end_time)

            if start_parsed:
                ts = f"{date_str} {start_parsed}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    (
                        f"{shift_code}_start",
                        ts,
                        start_user.strip() if start_user else "",
                        None,
                        None,
                        None,
                    ),
                )
                if start_user and start_user.strip():
                    all_personnel.add(start_user.strip())

            if end_parsed:
                ts = f"{date_str} {end_parsed}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    (f"{shift_code}_end", ts, end_user.strip() if end_user else "", None, None, None),
                )
                if end_user and end_user.strip():
                    all_personnel.add(end_user.strip())

        refill_str = row[13].strip() if len(row) > 13 and row[13] else ""
        if refill_str:
            try:
                refill_amount = float(refill_str)
                if refill_amount > 0:
                    driver = row[26].strip() if len(row) > 26 and row[26] else ""
                    receipt = row[15].strip() if len(row) > 15 and row[15] else ""

                    refill_time = "23:59:00"
                    for shift_code, start_time, end_time in reversed(shifts):
                        if _parse_time(end_time):
                            refill_time = _parse_time(end_time)
                            break

                    ts = f"{date_str} {refill_time}"
                    conn.execute(
                        "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                        ("refill", ts, "", str(refill_amount), driver, receipt),
                    )

                    if driver:
                        all_drivers.add(driver)
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося розпарсити refill в рядку {row_idx}: {e}")

        mnt_date = row[17].strip() if len(row) > 17 and row[17] else ""
        if mnt_date:
            hours_str = row[16].strip() if len(row) > 16 and row[16] else "0"
            try:
                hours = float(hours_str)
                conn.execute(
                    "INSERT INTO maintenance (date, type, hours, admin) VALUES (?,?,?,?)",
                    (date_str, "oil", hours, "import"),
                )
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося розпарсити maintenance в рядку {row_idx}: {e}")

    conn.commit()

    for driver in all_drivers:
        try:
            conn.execute("INSERT INTO drivers (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (driver,))
        except Exception:
            try:
                conn.execute("INSERT OR IGNORE INTO drivers (name) VALUES (?)", (driver,))
            except Exception:
                pass

    for person in all_personnel:
        try:
            conn.execute("INSERT INTO personnel_names (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (person,))
        except Exception:
            try:
                conn.execute("INSERT OR IGNORE INTO personnel_names (name) VALUES (?)", (person,))
            except Exception:
                pass

    conn.commit()
    conn.close()

    logger.info(f"✅ Імпортовано {len(data_rows)} рядків")
    logger.info(f"✅ Водіїв: {len(all_drivers)}, Персоналу: {len(all_personnel)}")


def _import_events_sheet(ss):
    """Імпорт з вкладки LOGS_SHEET_NAME (опціонально)."""
    title = _logs_sheet_name()
    try:
        events_sheet = ss.worksheet(title)
    except Exception:
        logger.info(f"ℹ️ Вкладка {title} не знайдена, пропускаємо")
        return

    logger.info(f"📥 Читаємо вкладку {title}...")

    all_values = events_sheet.get_all_values()
    if len(all_values) < 2:
        logger.info(f"ℹ️ Вкладка {title} порожня")
        return

    events_rows = all_values[1:]
    logger.info(f"ℹ️ Вкладка {title} містить {len(events_rows)} подій (не імпортуємо, щоб уникнути дублювання)")


def full_import():
    """Повний імпорт з Google Sheets в БД.

    БЕЗПЕЧНИЙ РЕЖИМ:
    1. Спочатку завантажуємо всі дані в пам'ять.
    2. Якщо помилка мережі/API — перериваємо, БД не чіпаємо.
    3. Якщо дані отримано — очищаємо БД і записуємо нові.
    """
    logger.info("📥 Починаємо імпорт з Sheets в БД (безпечний режим)...")

    try:
        # КРОК 1: Читання (може впасти)
        client = make_client()
        ss = open_spreadsheet(client)
        main_sheet = open_main_worksheet(ss)
        
        logger.info("📥 Завантаження даних з таблиці в пам'ять...")
        all_values = main_sheet.get_all_values()
        
        if len(all_values) < 3:
            logger.warning("⚠️ Таблиця виглядає порожньою (менше 3 рядків). Імпорт скасовано для безпеки.")
            return

        data_rows = all_values[2:]
        
    except Exception as e:
        logger.error(f"❌ Помилка підключення до Sheets. Імпорт скасовано, БД не змінено. Помилка: {e}")
        raise e

    # КРОК 2: Запис (тільки якщо крок 1 успішний)
    try:
        _clear_db()
        _import_main_sheet_data(data_rows)
        # _import_events_sheet(ss) # Опціонально, зараз вимкнено
        _restore_generator_state()
        
        logger.info("✅ Імпорт завершено успішно!")
        
    except Exception as e:
        logger.error(f"❌ Критична помилка під час запису в БД: {e}")
        raise e