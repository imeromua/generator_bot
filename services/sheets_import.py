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
    """Парсить дату, підтримує формати DD.MM.YYYY та YYYY-MM-DD."""
    if not date_str or not date_str.strip():
        return None
    
    s = date_str.strip()
    
    # Спроба 1: DD.MM.YYYY (стандарт для України)
    try:
        dt = datetime.strptime(s, "%d.%m.%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Спроба 2: YYYY-MM-DD (ISO формат, часто в Sheets)
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    return None


def _parse_time(time_str: str) -> str | None:
    """Парсить HH:MM в HH:MM:00"""
    if not time_str or not time_str.strip():
        return None
    try:
        parts = time_str.strip().split(":")
        if len(parts) == 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
        elif len(parts) == 3:
             return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}"
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

    # Зчитуємо логи
    cur.execute(
        """
        SELECT event_type, timestamp, value
        FROM logs
        ORDER BY timestamp ASC
    """
    )
    rows = cur.fetchall()

    # Зчитуємо останні ТО
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
    active_shifts = {}

    # Розрахунок стану (прокручуємо всі події)
    for event, ts_str, value in rows:
        if event == "refill":
            try:
                running_fuel += float(value or 0)
            except ValueError:
                pass
        elif event == "fuel_set":
            try:
                running_fuel = float(value or 0)
            except ValueError:
                pass
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
            try:
                running_hours = float(value or 0)
            except ValueError:
                pass

    # Шукаємо останні ТО
    last_oil = ""
    last_spark = ""

    for date_str, mnt_type, hours in mnt_rows:
        if mnt_type == "oil" and not last_oil:
            last_oil = date_str
        elif mnt_type == "spark" and not last_spark:
            last_spark = date_str
        if last_oil and last_spark:
            break

    # --- ЗАПИС В БД (ВИПРАВЛЕНО ДЛЯ POSTGRES) ---
    state_updates = [
        ("current_fuel", str(running_fuel)),
        ("total_hours", str(running_hours)),
        ("status", "OFF"),
        ("active_shift", "none")
    ]
    
    if last_oil:
        state_updates.append(("last_oil_change", last_oil))
    if last_spark:
        state_updates.append(("last_spark_change", last_spark))

    try:
        for k, v in state_updates:
            # Універсальний запит для Postgres та SQLite (Upsert)
            conn.execute(
                "INSERT INTO generator_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                (k, v)
            )
        
        conn.commit()
        logger.info(f"✅ Стан відновлено: паливо={running_fuel:.1f}л, мотогодини={running_hours:.1f}")

    except Exception as e:
        conn.rollback() # Відкочуємо транзакцію при помилці
        logger.error(f"❌ Помилка запису стану генератора: {e}")
        # Спроба оновити через UPDATE (якщо раптом ON CONFLICT не підтримується старою SQLite, хоча навряд)
        try:
            for k, v in state_updates:
                cur.execute("UPDATE generator_state SET value=? WHERE key=?", (v, k))
                if cur.rowcount == 0:
                    cur.execute("INSERT INTO generator_state (key, value) VALUES (?, ?)", (k, v))
            conn.commit()
        except Exception as ex_fallback:
            logger.error(f"❌ Fallback update failed: {ex_fallback}")
    finally:
        conn.close()


def _import_main_sheet_data(data_rows):
    """Імпорт даних, які вже зчитані з таблиці (без мережевих запитів)."""
    conn = get_connection()

    all_drivers = set()
    all_personnel = set()

    for row_idx, row in enumerate(data_rows, start=3):
        # Розширюємо рядок, щоб уникнути IndexError
        # Нам потрібно мінімум 29 колонок (0..28), бо AC - це index 28
        if len(row) < 30:
            row.extend([""] * (30 - len(row)))

        date_str = _parse_date(row[0])
        
        # --- ЗЧИТУВАННЯ ДОВІДНИКІВ (Навіть якщо дати немає) ---
        # Колонка AB (index 27) - Список водіїв
        driver_ref = row[27].strip()
        if driver_ref:
            # Можуть бути через кому
            for d in driver_ref.split(','):
                d_clean = d.strip()
                if d_clean:
                    all_drivers.add(d_clean)

        # Колонка AC (index 28) - Список персоналу
        personnel_ref = row[28].strip()
        if personnel_ref:
            for p in personnel_ref.split(','):
                p_clean = p.strip()
                if p_clean:
                    all_personnel.add(p_clean)

        if not date_str:
            continue

        # --- ЗМІНИ ---
        shifts = [
            ("m", row[1], row[2]),
            ("d", row[3], row[4]),
            ("e", row[5], row[6]),
            ("x", row[7], row[8]),
        ]

        shift_users = [
            (row[18], row[19]), # S, T
            (row[20], row[21]), # U, V
            (row[22], row[23]), # W, X
            (row[24], row[25]), # Y, Z
        ]

        for i, (shift_code, start_time, end_time) in enumerate(shifts):
            start_user, end_user = shift_users[i]

            start_parsed = _parse_time(start_time)
            end_parsed = _parse_time(end_time)

            if start_parsed:
                ts = f"{date_str} {start_parsed}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    (f"{shift_code}_start", ts, start_user.strip() if start_user else "", None, None, None),
                )

            if end_parsed:
                ts = f"{date_str} {end_parsed}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    (f"{shift_code}_end", ts, end_user.strip() if end_user else "", None, None, None),
                )

        # --- ЗАПРАВКИ ---
        refill_str = row[13].strip() if row[13] else ""
        if refill_str:
            try:
                # Видаляємо пробіли та коми
                refill_clean = refill_str.replace(",", ".").replace(" ", "")
                refill_amount = float(refill_clean)
                if refill_amount > 0:
                    # AA (index 26) - хто привіз паливо (в конкретний день)
                    driver = row[26].strip()
                    receipt = row[15].strip()

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

            except Exception as e:
                logger.warning(f"⚠️ Не вдалося розпарсити refill в рядку {row_idx}: {e}")

        # --- ТО (MAINTENANCE) ---
        mnt_date_raw = row[17].strip() # R
        if mnt_date_raw:
            hours_str = row[16].strip().replace(",", ".") if row[16] else "0"
            try:
                hours = float(hours_str)
                conn.execute(
                    "INSERT INTO maintenance (date, type, hours, admin) VALUES (?,?,?,?)",
                    (date_str, "oil", hours, "import"),
                )
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося розпарсити maintenance в рядку {row_idx}: {e}")

    conn.commit()

    # --- ЗАПИС ВОДІЇВ ---
    logger.info(f"🚙 Знайдено водіїв: {len(all_drivers)}")
    for driver in all_drivers:
        try:
            # Спроба для Postgres
            conn.execute("INSERT INTO drivers (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (driver,))
        except Exception:
            try:
                # Спроба для SQLite
                conn.execute("INSERT OR IGNORE INTO drivers (name) VALUES (?)", (driver,))
            except Exception:
                pass

    # --- ЗАПИС ПЕРСОНАЛУ ---
    logger.info(f"👥 Знайдено персоналу: {len(all_personnel)}")
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

    logger.info(f"✅ Імпортовано рядків: {len(data_rows)}")


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
        _restore_generator_state()
        
        logger.info("✅ Імпорт завершено успішно!")
        
    except Exception as e:
        logger.error(f"❌ Критична помилка під час запису в БД: {e}")
        raise e