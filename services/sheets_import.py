"""Модуль імпорту з Google Sheets в БД.

Актуальний шаблон (спрощений):
- Заголовок 1 рядок.
- Далі дані.
- Колонки "ПОЧАТОК, Г" / "КІНЕЦЬ, Г" повторюються 4 рази (для m/d/e/x) — їх треба брати по порядку.

Імпорт:
- Читаємо ТІЛЬКИ основну вкладку.
- НЕ читаємо/не відновлюємо з вкладки "ПОДІЇ".
- Відновлюємо logs тільки з рядків основної вкладки (часи змін + refills).
- Довідники водіїв/персоналу імпортуємо з колонок по НАЗВАХ.
- Службові колонки T/U (якщо є) ігноруємо.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Optional

import config
from database.models import get_connection, _is_postgres
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


def _fuel_rate() -> float:
    """Отримує витрати палива з config.

    Returns:
        Fuel consumption rate in liters per hour
    """
    try:
        return float(getattr(config, "FUEL_CONSUMPTION", 0.0) or 0.0)
    except Exception:
        return 0.0


def _parse_date(date_str: str) -> Optional[str]:
    """Парсить дату з різних форматів.

    Args:
        date_str: Date string

    Returns:
        Normalized date YYYY-MM-DD or None
    """
    if not date_str or not str(date_str).strip():
        return None

    s = str(date_str).strip()

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


def _parse_time(time_str: str) -> Optional[str]:
    """Парсить час з різних форматів.

    Args:
        time_str: Time string

    Returns:
        Normalized time HH:MM:SS or None
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


def _norm(s: str) -> str:
    """Нормалізує рядок для порівняння.

    Args:
        s: Input string

    Returns:
        Normalized lowercase string
    """
    return (s or "").strip().lower().replace("\n", " ")


def _is_service_col_header(label_norm: str) -> bool:
    """Перевіряє чи це службовий заголовок.

    Args:
        label_norm: Normalized label

    Returns:
        True if service column
    """
    if not label_norm:
        return True
    if label_norm in {"t", "u"}:
        return True
    if "служб" in label_norm:
        return True
    return False


def _build_header_map_1row(header: list[str]) -> dict[str, list[int]]:
    """Map normalized header label -> list of column indices (to support duplicates).

    Args:
        header: Header row from spreadsheet

    Returns:
        Dict mapping normalized label to list of column indices
    """
    m: dict[str, list[int]] = {}
    for i, col in enumerate(header):
        n = _norm(col)
        if _is_service_col_header(n):
            continue
        if not n:
            continue
        m.setdefault(n, []).append(i)
    return m


def _get(row: list[str], idx: Optional[int]) -> str:
    """Безпечне отримання значення з рядка.

    Args:
        row: Row from spreadsheet
        idx: Column index

    Returns:
        Cell value or empty string
    """
    if idx is None or idx < 0:
        return ""
    return (row[idx] if idx < len(row) else "") or ""


def _clear_db() -> None:
    """Очищує БД перед імпортом."""
    logger.info("🧹 Очищуємо БД перед імпортом...")
    with get_connection() as conn:
        conn.execute("DELETE FROM logs")
        conn.execute("DELETE FROM schedule")
        conn.execute("DELETE FROM maintenance")
        conn.execute("DELETE FROM drivers")
        conn.execute("DELETE FROM personnel_names")
        conn.execute("DELETE FROM user_personnel")
        conn.commit()
    logger.info("✅ БД очищено")


def _restore_generator_state() -> None:
    """Відновлює стан генератора з логів."""
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
    active_shifts: dict[str, str] = {}

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
                except Exception as e:
                    logger.debug(f"Failed to restore shift delta for {shift}: {e}", exc_info=True)
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
        except Exception as re:
            logger.debug(f"Rollback failed in _restore_generator_state: {re}", exc_info=True)
        logger.error(f"❌ Помилка запису стану генератора: {e}")
    finally:
        conn.close()


def _import_main_sheet_data(all_values: list[list[str]]) -> None:
    """Імпортує дані з основної вкладки.

    Args:
        all_values: All rows from main worksheet
    """
    if len(all_values) < 2:
        logger.warning("⚠️ Таблиця виглядає порожньою (менше 2 рядків).")
        return

    header = all_values[0]
    data_rows = all_values[1:]

    hmap = _build_header_map_1row(header)

    def idx_first(name: str) -> Optional[int]:
        arr = hmap.get(_norm(name))
        return arr[0] if arr else None

    def idx_n(name: str, n: int) -> Optional[int]:
        arr = hmap.get(_norm(name))
        return arr[n] if arr and len(arr) > n else None

    idx_date = idx_first("дата")

    # 4 shifts from duplicates by order
    idx_m_start = idx_n("початок, г", 0)
    idx_m_end = idx_n("кінець, г", 0)
    idx_d_start = idx_n("початок, г", 1)
    idx_d_end = idx_n("кінець, г", 1)
    idx_e_start = idx_n("початок, г", 2)
    idx_e_end = idx_n("кінець, г", 2)
    idx_x_start = idx_n("початок, г", 3)
    idx_x_end = idx_n("кінець, г", 3)

    idx_refill = idx_first("привезено палива")
    idx_receipt = idx_first("номер чека")
    idx_driver_day = idx_first("паливо превіз")

    idx_drivers_dict = idx_first("водіїї")
    idx_personnel_dict = idx_first("персонал")

    logger.info(
        "📌 Header map найдено: "
        f"date={idx_date}, m=({idx_m_start},{idx_m_end}), d=({idx_d_start},{idx_d_end}), "
        f"e=({idx_e_start},{idx_e_end}), x=({idx_x_start},{idx_x_end}), "
        f"refill={idx_refill}, receipt={idx_receipt}, driver_day={idx_driver_day}, "
        f"drivers_dict={idx_drivers_dict}, personnel_dict={idx_personnel_dict}"
    )

    if idx_date is None:
        logger.warning("⚠️ Не знайдено колонку 'ДАТА' у заголовку. Імпорт скасовано.")
        return

    conn = get_connection()
    all_drivers: set[str] = set()
    all_personnel: set[str] = set()

    def _insert_driver(conn_: sqlite3.Connection, name: str) -> None:
        if _is_postgres():
            conn_.execute("INSERT INTO drivers (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (name,))
        else:
            conn_.execute("INSERT OR IGNORE INTO drivers (name) VALUES (?)", (name,))

    def _insert_personnel(conn_: sqlite3.Connection, name: str) -> None:
        if _is_postgres():
            conn_.execute("INSERT INTO personnel_names (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (name,))
        else:
            conn_.execute("INSERT OR IGNORE INTO personnel_names (name) VALUES (?)", (name,))

    for row in data_rows:
        driver_ref = _get(row, idx_drivers_dict).strip()
        if driver_ref:
            for d in driver_ref.split(","):
                d_clean = d.strip()
                if d_clean:
                    all_drivers.add(d_clean)

        personnel_ref = _get(row, idx_personnel_dict).strip()
        if personnel_ref:
            for p in personnel_ref.split(","):
                p_clean = p.strip()
                if p_clean:
                    all_personnel.add(p_clean)

        date_str = _parse_date(_get(row, idx_date))
        if not date_str:
            continue

        shifts = [
            ("m", _get(row, idx_m_start), _get(row, idx_m_end)),
            ("d", _get(row, idx_d_start), _get(row, idx_d_end)),
            ("e", _get(row, idx_e_start), _get(row, idx_e_end)),
            ("x", _get(row, idx_x_start), _get(row, idx_x_end)),
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

        refill_str = _get(row, idx_refill).strip()
        if refill_str:
            try:
                refill_amount = float(refill_str.replace(",", ".").replace(" ", ""))
            except Exception:
                refill_amount = 0.0

            if refill_amount > 0:
                driver_day = _get(row, idx_driver_day).strip()
                receipt = _get(row, idx_receipt).strip()

                refill_time = "23:59:00"
                for _shift_code, _st, _en in reversed(shifts):
                    en_p = _parse_time(_en)
                    if en_p:
                        refill_time = en_p
                        break

                ts = f"{date_str} {refill_time}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    ("refill", ts, "", str(refill_amount), driver_day, receipt),
                )

    for d in all_drivers:
        try:
            _insert_driver(conn, d)
        except Exception as e:
            logger.warning(f"Failed to insert driver '{d}': {e}")

    for p in all_personnel:
        try:
            _insert_personnel(conn, p)
        except Exception as e:
            logger.warning(f"Failed to insert personnel '{p}': {e}")

    conn.commit()
    conn.close()

    logger.info(f"✅ Імпортовано рядків: {len(data_rows)}")
    logger.info(f"🚙 Імпортовано водіїв (довідник): {len(all_drivers)}")
    logger.info(f"👥 Імпортовано персонал (довідник): {len(all_personnel)}")


def full_import() -> None:
    """Виконує повний імпорт з Sheets в БД.

    IMPORTANT: Clears database before import!
    """
    logger.info("📥 Починаємо імпорт з Sheets в БД (безпечний режим)...")

    try:
        client = make_client()
        ss = open_spreadsheet(client)
        main_sheet = open_main_worksheet(ss)

        logger.info("📥 Завантаження даних з таблиці в пам'ять...")
        all_values = main_sheet.get_all_values()

        if len(all_values) < 2:
            logger.warning("⚠️ Таблиця виглядає порожньою (менше 2 рядків). Імпорт скасовано для безпеки.")
            return

    except Exception as e:
        logger.error(f"❌ Помилка підключення до Sheets. Імпорт скасовано, БД не змінено. Помилка: {e}")
        raise

    try:
        _clear_db()
        _import_main_sheet_data(all_values)
        _restore_generator_state()
        logger.info("✅ Імпорт завершено успішно!")

    except Exception as e:
        logger.error(f"❌ Критична помилка під час запису в БД: {e}")
        raise
