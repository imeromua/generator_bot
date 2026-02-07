"""Модуль імпорту з Google Sheets в БД.

Читає дані з основної вкладки (A-AC) і вкладки ПОДІЇ.
Відновлює logs, maintenance, drivers, personnel в БД.
"""

import logging
from datetime import datetime

import config
from database.models import get_connection
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


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
        # Перевіряємо формат
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


def _import_main_sheet(sheet):
    """Імпорт з основної вкладки (A-AC)"""
    logger.info("📥 Читаємо основну вкладку...")
    
    # Читаємо всі дані (починаючи з рядка 3, перші 2 — шапка)
    all_values = sheet.get_all_values()
    
    if len(all_values) < 3:
        logger.warning("⚠️ Таблиця порожня або немає даних")
        return
    
    data_rows = all_values[2:]  # Пропускаємо шапку
    
    conn = get_connection()
    
    # Множини для водіїв і персоналу
    all_drivers = set()
    all_personnel = set()
    
    for row_idx, row in enumerate(data_rows, start=3):
        if len(row) < 29:  # Принаймні до AC (29 колонок: A-AC)
            # Доповнюємо порожніми комірками
            row.extend([""] * (29 - len(row)))
        
        # A: дата
        date_str = _parse_date(row[0])
        if not date_str:
            continue  # Пропускаємо порожні рядки
        
        # B-I: часи старт/стоп змін (m/d/e/x)
        shifts = [
            ('m', row[1], row[2]),   # B-C
            ('d', row[3], row[4]),   # D-E
            ('e', row[5], row[6]),   # F-G
            ('x', row[7], row[8]),   # H-I
        ]
        
        # S-Z: відповідальні за зміни (start_user, end_user)
        shift_users = [
            (row[18], row[19]),  # S-T (зміна 1 = m)
            (row[20], row[21]),  # U-V (зміна 2 = d)
            (row[22], row[23]),  # W-X (зміна 3 = e)
            (row[24], row[25]),  # Y-Z (зміна 4 = x)
        ]
        
        # Записуємо зміни в logs
        for i, (shift_code, start_time, end_time) in enumerate(shifts):
            start_user, end_user = shift_users[i]
            
            start_parsed = _parse_time(start_time)
            end_parsed = _parse_time(end_time)
            
            if start_parsed:
                ts = f"{date_str} {start_parsed}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    (f"{shift_code}_start", ts, start_user.strip() if start_user else "", None, None, None)
                )
                if start_user and start_user.strip():
                    all_personnel.add(start_user.strip())
            
            if end_parsed:
                ts = f"{date_str} {end_parsed}"
                conn.execute(
                    "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                    (f"{shift_code}_end", ts, end_user.strip() if end_user else "", None, None, None)
                )
                if end_user and end_user.strip():
                    all_personnel.add(end_user.strip())
        
        # N: привезено палива
        refill_str = row[13].strip() if len(row) > 13 and row[13] else ""
        if refill_str:
            try:
                refill_amount = float(refill_str)
                if refill_amount > 0:
                    # AA: хто привіз паливо
                    driver = row[26].strip() if len(row) > 26 and row[26] else ""
                    # P: номер чека
                    receipt = row[15].strip() if len(row) > 15 and row[15] else ""
                    
                    # Час refill — кінець останньої зміни або 23:59
                    refill_time = "23:59:00"
                    for shift_code, start_time, end_time in reversed(shifts):
                        if _parse_time(end_time):
                            refill_time = _parse_time(end_time)
                            break
                    
                    ts = f"{date_str} {refill_time}"
                    conn.execute(
                        "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                        ("refill", ts, "", str(refill_amount), driver, receipt)
                    )
                    
                    if driver:
                        all_drivers.add(driver)
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося розпарсити refill в рядку {row_idx}: {e}")
        
        # R: ТО дата
        mnt_date = row[17].strip() if len(row) > 17 and row[17] else ""
        if mnt_date:
            # Q: мотогодини
            hours_str = row[16].strip() if len(row) > 16 and row[16] else "0"
            try:
                hours = float(hours_str)
                # Записуємо в maintenance (тип = oil або spark, визначити не можемо, тож пишемо "oil")
                conn.execute(
                    "INSERT INTO maintenance (date, type, hours, admin) VALUES (?,?,?,?)",
                    (date_str, "oil", hours, "import")
                )
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося розпарсити maintenance в рядку {row_idx}: {e}")
    
    conn.commit()
    
    # Записуємо водіїв і персонал
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
    """Імпорт з вкладки ПОДІЇ (опціонально)"""
    try:
        events_sheet = ss.worksheet("ПОДІЇ")
    except Exception:
        logger.info("ℹ️ Вкладка ПОДІЇ не знайдена, пропускаємо")
        return
    
    logger.info("📥 Читаємо вкладку ПОДІЇ...")
    
    all_values = events_sheet.get_all_values()
    if len(all_values) < 2:
        logger.info("ℹ️ Вкладка ПОДІЇ порожня")
        return
    
    # Формат: [Дата, Час, Подія, Користувач, Значення, Водій, Чек]
    # Пропускаємо шапку
    events_rows = all_values[1:]
    
    # Просто логуємо кількість, не імпортуємо (щоб не дублювати)
    logger.info(f"ℹ️ Вкладка ПОДІЇ містить {len(events_rows)} подій (не імпортуємо, щоб уникнути дублювання)")


def full_import():
    """Повний імпорт з Google Sheets в БД.
    
    Читає:
    - Основну вкладку (A-AC)
    - Вкладку ПОДІЇ (опціонально)
    
    Відновлює logs, maintenance, drivers, personnel в БД.
    """
    logger.info("📥 Починаємо імпорт з Sheets в БД...")
    
    # Очищаємо БД
    _clear_db()
    
    # Підключаємось до Sheets
    client = make_client()
    ss = open_spreadsheet(client)
    main_sheet = open_main_worksheet(ss)
    
    # Імпортуємо основну вкладку
    _import_main_sheet(main_sheet)
    
    # Імпортуємо вкладку ПОДІЇ (опціонально)
    _import_events_sheet(ss)
    
    logger.info("✅ Імпорт завершено!")
