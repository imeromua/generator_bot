"""Модуль експорту з БД в Google Sheets.

Формат експорту (A-AC):
- A = дата (DD.MM.YYYY)
- B-I = часи старт/стоп по змінах (HH:MM)
- J = всього годин за день (HH:MM)
- K = залишок палива на ранок
- L = витрати палива за день
- M = залишок після витрат
- N = привезено палива
- O = залишок палива ввечері
- P = номер чека (receipt_number)
- Q = мотогодини на кінець дня
- R = ТО дата (тільки в день заміни)
- S-T = відповідальні за зміну 1
- U-V = відповідальні за зміну 2
- W-X = відповідальні за зміну 3
- Y-Z = відповідальні за зміну 4
- AA = хто привіз паливо (driver)
- AB = водії (список через кому)
- AC = персонал (список через кому)
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

import config
import database.db_api as db
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


def _parse_ts(ts_str: str) -> datetime | None:
    """Парсить timestamp з БД (YYYY-MM-DD HH:MM:SS)"""
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _time_to_hhmm(dt: datetime | None) -> str:
    """Конвертує datetime в HH:MM"""
    if not dt:
        return ""
    return dt.strftime("%H:%M")


def _hours_to_hhmm(hours: float) -> str:
    """Конвертує часи (десяткове число) в HH:MM"""
    if hours <= 0:
        return "00:00"
    h = int(hours)
    m = int((hours - h) * 60)
    return f"{h:02d}:{m:02d}"


def _aggregate_logs_by_date():
    """Зчитує всі логи з БД і групує по датах.
    
    Повертає dict[date_str] = {
        'shifts': { 'm': {'start': dt, 'end': dt, 'start_user': str, 'end_user': str}, ... },
        'refills': [(amount, driver, receipt), ...],
        'maintenance': [(type, hours), ...],
        'total_hours_end': float,
        'fuel_start': float,
        'fuel_end': float,
    }
    """
    conn = db.get_connection()
    cur = conn.cursor()
    
    # Читаємо всі логи (сортуємо по часу)
    cur.execute("""
        SELECT event_type, timestamp, user_name, value, driver_name, receipt_number
        FROM logs
        ORDER BY timestamp ASC
    """)
    rows = cur.fetchall()
    
    # Читаємо maintenance
    cur.execute("""
        SELECT date, type, hours
        FROM maintenance
        ORDER BY date ASC
    """)
    mnt_rows = cur.fetchall()
    
    conn.close()
    
    # Структура даних по датах
    days = defaultdict(lambda: {
        'shifts': {'m': {}, 'd': {}, 'e': {}, 'x': {}},
        'refills': [],
        'maintenance': [],
        'total_hours_end': 0.0,
        'fuel_start': 0.0,
        'fuel_end': 0.0,
    })
    
    # Обробляємо логи
    running_hours = 0.0
    running_fuel = 0.0
    
    for row in rows:
        event, ts_str, user, value, driver, receipt = row
        dt = _parse_ts(ts_str)
        if not dt:
            continue
        
        date_str = dt.strftime("%Y-%m-%d")
        day = days[date_str]
        
        # Старт/стоп змін
        if event.endswith('_start'):
            shift = event.split('_')[0]  # m/d/e/x
            day['shifts'][shift]['start'] = dt
            day['shifts'][shift]['start_user'] = user or ""
        
        elif event.endswith('_end'):
            shift = event.split('_')[0]
            day['shifts'][shift]['end'] = dt
            day['shifts'][shift]['end_user'] = user or ""
            
            # Обчислюємо години
            start = day['shifts'][shift].get('start')
            end = day['shifts'][shift].get('end')
            if start and end:
                delta = (end - start).total_seconds() / 3600.0
                running_hours += delta
        
        # Заправка
        elif event == 'refill':
            amount = float(value or 0)
            running_fuel += amount
            day['refills'].append((amount, driver or "", receipt or ""))
        
        # Корекція палива
        elif event == 'fuel_set':
            running_fuel = float(value or 0)
        
        # Корекція мотогодин
        elif event == 'total_hours_set':
            running_hours = float(value or 0)
        
        # Зберігаємо стан на кінець дня
        day['total_hours_end'] = running_hours
        day['fuel_end'] = running_fuel
    
    # Обробляємо maintenance
    for row in mnt_rows:
        date_str, mnt_type, hours = row
        if date_str in days:
            days[date_str]['maintenance'].append((mnt_type, hours))
    
    # Обчислюємо fuel_start для кожного дня (залишок попереднього дня)
    sorted_dates = sorted(days.keys())
    prev_fuel = 0.0
    for d in sorted_dates:
        days[d]['fuel_start'] = prev_fuel
        prev_fuel = days[d]['fuel_end']
    
    return days


def _build_export_rows(days_data):
    """Будує рядки для експорту (A-AC)"""
    rows = []
    
    sorted_dates = sorted(days_data.keys())
    
    for date_str in sorted_dates:
        day = days_data[date_str]
        
        # A: дата (DD.MM.YYYY)
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_fmt = dt.strftime("%d.%m.%Y")
        
        row = [date_fmt]
        
        # B-I: часи старт/стоп по змінах (m/d/e/x)
        for shift in ['m', 'd', 'e', 'x']:
            s = day['shifts'].get(shift, {})
            row.append(_time_to_hhmm(s.get('start')))
            row.append(_time_to_hhmm(s.get('end')))
        
        # J: всього годин за день
        total_day_hours = 0.0
        for shift in ['m', 'd', 'e', 'x']:
            s = day['shifts'].get(shift, {})
            start = s.get('start')
            end = s.get('end')
            if start and end:
                delta = (end - start).total_seconds() / 3600.0
                total_day_hours += delta
        row.append(_hours_to_hhmm(total_day_hours))
        
        # K: залишок палива на ранок
        fuel_start = day['fuel_start']
        row.append(f"{fuel_start:.1f}" if fuel_start > 0 else "")
        
        # L: витрати палива (обчислюється як 0.8л/год)
        fuel_consumed = total_day_hours * 0.8
        row.append(f"{fuel_consumed:.1f}" if fuel_consumed > 0 else "")
        
        # M: залишок після витрат
        fuel_after = fuel_start - fuel_consumed
        row.append(f"{fuel_after:.1f}" if fuel_after != 0 else "")
        
        # N: привезено палива (сума refill)
        total_refill = sum(r[0] for r in day['refills'])
        row.append(f"{total_refill:.1f}" if total_refill > 0 else "")
        
        # O: залишок ввечері
        fuel_end = day['fuel_end']
        row.append(f"{fuel_end:.1f}" if fuel_end > 0 else "")
        
        # P: номер чека (перший receipt_number з refill)
        receipt = ""
        if day['refills']:
            receipt = day['refills'][0][2]  # (amount, driver, receipt)
        row.append(receipt or "")
        
        # Q: мотогодини на кінець дня
        row.append(f"{day['total_hours_end']:.1f}" if day['total_hours_end'] > 0 else "")
        
        # R: ТО дата (тільки в день заміни)
        mnt_date = ""
        if day['maintenance']:
            mnt_date = date_fmt  # Дата ТО = дата рядка
        row.append(mnt_date)
        
        # S-Z: відповідальні за зміни (start_user, end_user)
        for shift in ['m', 'd', 'e', 'x']:
            s = day['shifts'].get(shift, {})
            row.append(s.get('start_user', ""))
            row.append(s.get('end_user', ""))
        
        # AA: хто привіз паливо (перший driver з refill)
        driver = ""
        if day['refills']:
            driver = day['refills'][0][1]
        row.append(driver or "")
        
        # AB: водії (список унікальних drivers з refill)
        drivers = list(set(r[1] for r in day['refills'] if r[1]))
        row.append(", ".join(drivers) if drivers else "")
        
        # AC: персонал (список унікальних users зі змін)
        users = set()
        for shift in ['m', 'd', 'e', 'x']:
            s = day['shifts'].get(shift, {})
            if s.get('start_user'):
                users.add(s['start_user'])
            if s.get('end_user'):
                users.add(s['end_user'])
        row.append(", ".join(sorted(users)) if users else "")
        
        rows.append(row)
    
    return rows


def _build_events_rows():
    """Будує рядки для вкладки ПОДІЇ (всі логи)"""
    conn = db.get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT event_type, timestamp, user_name, value, driver_name, receipt_number
        FROM logs
        ORDER BY timestamp ASC
    """)
    rows = cur.fetchall()
    conn.close()
    
    events = []
    for row in rows:
        event, ts_str, user, value, driver, receipt = row
        dt = _parse_ts(ts_str)
        if not dt:
            continue
        
        # Формат: [дата, час, подія, користувач, значення, водій, чек]
        events.append([
            dt.strftime("%d.%m.%Y"),
            dt.strftime("%H:%M:%S"),
            event,
            user or "",
            value or "",
            driver or "",
            receipt or ""
        ])
    
    return events


def full_export():
    """Повний експорт з БД в Google Sheets.
    
    Записує:
    - Основну вкладку (A-AC)
    - Вкладку ПОДІЇ (всі логи)
    """
    logger.info("📤 Починаємо експорт з БД в Sheets...")
    
    # Агрегуємо дані
    days_data = _aggregate_logs_by_date()
    
    # Будуємо рядки
    main_rows = _build_export_rows(days_data)
    events_rows = _build_events_rows()
    
    logger.info(f"📄 Підготовлено {len(main_rows)} рядків для основної вкладки")
    logger.info(f"📄 Підготовлено {len(events_rows)} подій")
    
    # Підключаємось до Sheets
    client = make_client()
    ss = open_spreadsheet(client)
    main_sheet = open_main_worksheet(ss)
    
    # Записуємо основну вкладку (починаємо з рядка 3, перші 2 — шапка)
    if main_rows:
        start_row = 3
        main_sheet.update(
            f"A{start_row}:AC{start_row + len(main_rows) - 1}",
            main_rows,
            value_input_option="USER_ENTERED"
        )
        logger.info(f"✅ Основна вкладка оновлена ({len(main_rows)} рядків)")
    
    # Записуємо вкладку ПОДІЇ
    try:
        events_sheet = ss.worksheet("ПОДІЇ")
    except Exception:
        # Створюємо, якщо немає
        events_sheet = ss.add_worksheet("ПОДІЇ", rows=1000, cols=7)
        # Шапка
        events_sheet.update("A1:G1", [["Дата", "Час", "Подія", "Користувач", "Значення", "Водій", "Чек"]])
    
    if events_rows:
        events_sheet.clear()
        # Шапка + дані
        all_events = [["Дата", "Час", "Подія", "Користувач", "Значення", "Водій", "Чек"]] + events_rows
        events_sheet.update("A1", all_events, value_input_option="USER_ENTERED")
        logger.info(f"✅ Вкладка ПОДІЇ оновлена ({len(events_rows)} подій)")
    
    logger.info("✅ Експорт завершено!")
