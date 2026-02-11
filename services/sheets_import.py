"""Модуль імпорту з Google Sheets в БД.

Остаточний шаблон імпорту (без вкладки "ПОДІЇ"):
- Читаємо ТІЛЬКИ основну вкладку.
- НЕ відновлюємо logs з окремої вкладки подій.
- Відновлюємо logs тільки з даних основної вкладки: часи старт/стоп змін + refills.

Важливо:
- Витрата палива береться з ENV через config.FUEL_CONSUMPTION.
- Назва вкладки логів LOGS_SHEET_NAME більше не використовується для імпорту.
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


def _parse_date(date_str: str) -> str | None:
    """Парсить дату, підтримує формати DD.MM.YYYY та YYYY-MM-DD."""
    if not date_str or not date_str.strip():
        return None

    s = date_str.strip()

    try:
        dt = datetime.strptime(s, "%d.%m.%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    return None


def _parse_time(time_str: str) -> str | None:
    """Парсить час з Sheets у HH:MM:SS.

    Приймає HH:MM, HH:MM:SS, а також значення, що можуть прийти як 08:50:00.
    """
    if not time_str or not str(time_str).strip():
        return None
    try:
        s = str(time_str).strip().replace('"', "")
        parts = s.split(":")
        if len(parts) == 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
        if len(parts) == 3:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}"
        return None
    except Exception:
        return None


def _clear_db():
    """Очищає БД перед імпортом."""
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

    rate = _fuel_rate()

    running_fuel = 0.0
    running_hours = 0.0
    active_shifts = {}

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

    state_updates = [
        ("current_fuel", str(running_fuel)),
        ("total_hours", str(running_hours)),
        ("status", "OFF"),
        ("active_shift", "none"),
    ]

    try:
        for k, v in state_updates:
            conn.execute(
                "INSERT INTO generator_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, v),
            )
        conn.commit()
        logger.info(f"✅ Стан відновлено: паливо={running_fuel:.1f}л, мотогодини={running_hours:.1f}")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"❌ Помилка запису стану генератора: {e}")
    finally:
        conn.close()


def _import_main_sheet_data(data_rows):
    """Імпорт даних з основної вкладки (без вкладки подій)."""
    conn = get_connection()

    all_drivers = set()
    all_personnel = set()

    for row_idx, row in enumerate(data_rows, start=3):
        # Нам потрібні AB (index 27) і AC (28) для довідників
        if len(row) < 29:
            row.extend([""] * (29 - len(row)))

        date_str = _parse_date(row[0])

        # Довідники: AB=водії, AC=персонал (беремо завжди, навіть якщо дати нема)
        driver_ref = (row[27] or "").strip()
        if driver_ref:
            for d in driver_ref.split(","):
                d_clean = d.strip()
                if d_clean:
                    all_drivers.add(d_clean)

        personnel_ref = (row[28] or "").strip()
        if personnel_ref:
            for p in personnel_ref.split(","):
                p_clean = p.strip()
                if p_clean:
                    all_personnel.add(p_clean)

        if not date_str:
            continue

        # Зміни: беремо тільки часи, відповідальних не імпортуємо
        shifts = [
            ("m", row[1], row[2]),
            ("d", row[3], row[4]),
            ("e", row[5], row[6]),
            ("x", row[7], row[8]),
        ]

        for shift_code, start_time, end_time in shifts:
            start_parsed = _parse_time(start_time)
            end_parsed = _parse_time(end_time)

            if start_parsed:
                ts = f"{date_str} {start_parsed}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    (f"{shift_code}_start", ts, "", None, None, None),
                )

            if end_parsed:
                ts = f"{date_str} {end_parsed}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    (f"{shift_code}_end", ts, "", None, None, None),
                )

        # Заправки (один запис на день)
        refill_str = (row[13] or "").strip()  # N
        if refill_str:
            try:
                refill_amount = float(refill_str.replace(",", ".").replace(" ", ""))
            except Exception:
                refill_amount = 0.0

            if refill_amount > 0:
                driver = (row[26] or "").strip()  # AA
                receipt = (row[15] or "").strip()  # P

                refill_time = "23:59:00"
                for _shift_code, _st, _en in reversed(shifts):
                    en_p = _parse_time(_en)
                    if en_p:
                        refill_time = en_p
                        break

                ts = f"{date_str} {refill_time}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    ("refill", ts, "", str(refill_amount), driver, receipt),
                )

    # Запис довідників: тут була помилка — conn був закритий до вставок у попередніх версіях
    # Тепер вставляємо ДО conn.close().
    for driver in all_drivers:
        try:
            conn.execute("INSERT OR IGNORE INTO drivers (name) VALUES (?)", (driver,))
        except Exception:
            try:
                # Postgres / загальний варіант
                conn.execute("INSERT INTO drivers (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (driver,))
            except Exception:
                try:
                    conn.execute("INSERT INTO drivers (name) VALUES (?)", (driver,))
                except Exception:
                    pass

    for person in all_personnel:
        try:
            conn.execute("INSERT OR IGNORE INTO personnel_names (name) VALUES (?)", (person,))
        except Exception:
            try:
                conn.execute(
                    "INSERT INTO personnel_names (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
                    (person,),
                )
            except Exception:
                try:
                    conn.execute("INSERT INTO personnel_names (name) VALUES (?)", (person,))
                except Exception:
                    pass

    conn.commit()
    conn.close()

    logger.info(f"✅ Імпортовано рядків: {len(data_rows)}")
    logger.info(f"🚙 Імпортовано водіїв (довідник): {len(all_drivers)}")
    logger.info(f"👥 Імпортовано персонал (довідник): {len(all_personnel)}")


def full_import():
    """Повний імпорт з Google Sheets в БД (тільки основна вкладка)."""
    logger.info("📥 Починаємо імпорт з Sheets в БД (безпечний режим)...")

    try:
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
        raise

    try:
        _clear_db()
        _import_main_sheet_data(data_rows)
        _restore_generator_state()
        logger.info("✅ Імпорт завершено успішно!")

    except Exception as e:
        logger.error(f"❌ Критична помилка під час запису в БД: {e}")
        raise
