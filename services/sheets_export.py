"""Модуль експорту з БД в Google Sheets.

Формат експорту (A-Q):
- A = дата (DD.MM.YYYY)
- B-I = часи старт/стоп по змінах (HH:MM)
- J = всього годин за день (HH:MM)
- K = залишок палива на ранок
- L = витрати палива за день
- M = залишок після витрат
- N = привезено палива
- O = залишок палива ввечері
- P = номер чека (receipt_number) (перший за день)
- Q = хто привіз паливо (driver) (перший за день)

Експорт інкрементальний:
- Знаходимо останню дату в Sheets
- Експортуємо тільки дні >= цієї дати (оновлюємо поточний + дописуємо нові)

Важливо:
- Витрата палива береться з ENV через config.FUEL_CONSUMPTION.
- Назва вкладки логів береться з ENV через config.LOGS_SHEET_NAME.
"""

import logging
from collections import defaultdict
from datetime import datetime

import config
import database.db_api as db
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


def _fuel_rate() -> float:
    """Єдине джерело правди для витрати палива (л/год)"""
    try:
        return float(getattr(config, "FUEL_CONSUMPTION", 0.0) or 0.0)
    except Exception:
        return 0.0


def _logs_sheet_name() -> str:
    """Єдине джерело правди для назви вкладки подій."""
    return (getattr(config, "LOGS_SHEET_NAME", None) or "ПОДІЇ").strip() or "ПОДІЇ"


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
    m = int(round((hours - h) * 60))
    if m == 60:
        h += 1
        m = 0
    return f"{h:02d}:{m:02d}"


def _find_last_date_in_sheet(sheet) -> str | None:
    """Знаходить останню дату в колонці A (формат DD.MM.YYYY).

    Повертає дату у форматі YYYY-MM-DD або None якщо таблиця порожня.
    """
    try:
        col_a = sheet.col_values(1)

        if len(col_a) < 3:
            logger.info("📋 Sheets порожня, експортуємо всі дані")
            return None

        data_rows = col_a[2:]

        last_date_str = None
        for cell in reversed(data_rows):
            if cell and cell.strip():
                last_date_str = cell.strip()
                break

        if not last_date_str:
            logger.info("📋 Немає даних в Sheets, експортуємо всі дані")
            return None

        try:
            dt = datetime.strptime(last_date_str, "%d.%m.%Y")
            result = dt.strftime("%Y-%m-%d")
            logger.info(f"📅 Остання дата в Sheets: {last_date_str} ({result})")
            return result
        except Exception as e:
            logger.warning(f"⚠️ Не вдалося розпарсити останню дату '{last_date_str}': {e}")
            return None

    except Exception as e:
        logger.error(f"❌ Помилка пошуку останньої дати: {e}")
        return None


def _get_fuel_before_date(from_date: str) -> float:
    """Знаходить fuel_end з дня ПЕРЕД from_date.

    Це потрібно для правильного розрахунку fuel_start при інкрементальному експорті.
    Враховує витрати палива!
    """
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT event_type, timestamp, value
        FROM logs
        WHERE timestamp < ?
        ORDER BY timestamp ASC
    """,
        (f"{from_date} 00:00:00",),
    )

    rows = cur.fetchall()
    conn.close()

    rate = _fuel_rate()

    running_fuel = 0.0
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
                    running_fuel -= delta * rate
                except Exception:
                    pass
                del active_shifts[shift]

    logger.info(f"🛢 Залишок палива перед {from_date}: {running_fuel:.1f}л")
    return running_fuel


def _aggregate_logs_by_date(from_date: str | None = None):
    """Зчитує всі логи з БД і групує по датах.

    Якщо from_date вказано, бере тільки дні >= from_date.

    Повертає dict[date_str] = {
        'shifts': { 'm': {'start': dt, 'end': dt}, ... },
        'refills': [(amount, driver, receipt), ...],
        'fuel_start': float,
        'fuel_end': float,
    }
    """
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT event_type, timestamp, user_name, value, driver_name, receipt_number
        FROM logs
        ORDER BY timestamp ASC
    """
    )
    rows = cur.fetchall()
    conn.close()

    days = defaultdict(
        lambda: {
            "shifts": {"m": {}, "d": {}, "e": {}, "x": {}},
            "refills": [],
            "fuel_start": 0.0,
            "fuel_end": 0.0,
        }
    )

    rate = _fuel_rate()

    running_fuel = 0.0

    for event, ts_str, user, value, driver, receipt in rows:
        dt = _parse_ts(ts_str)
        if not dt:
            continue

        date_str = dt.strftime("%Y-%m-%d")
        day = days[date_str]

        if event.endswith("_start"):
            shift = event.split("_")[0]
            day["shifts"][shift]["start"] = dt

        elif event.endswith("_end"):
            shift = event.split("_")[0]
            day["shifts"][shift]["end"] = dt

            start = day["shifts"][shift].get("start")
            end = day["shifts"][shift].get("end")
            if start and end:
                delta = (end - start).total_seconds() / 3600.0
                running_fuel -= delta * rate

        elif event == "refill":
            amount = float(value or 0)
            running_fuel += amount
            day["refills"].append((amount, driver or "", receipt or ""))

        elif event == "fuel_set":
            running_fuel = float(value or 0)

        day["fuel_end"] = running_fuel

    sorted_dates = sorted(days.keys())

    if from_date:
        prev_fuel = _get_fuel_before_date(from_date)
    else:
        prev_fuel = 0.0

    for d in sorted_dates:
        days[d]["fuel_start"] = prev_fuel
        prev_fuel = days[d]["fuel_end"]

    if from_date:
        days = {d: data for d, data in days.items() if d >= from_date}

    return days


def _build_export_rows(days_data):
    """Будує рядки для експорту (A-Q)."""
    rows = []

    sorted_dates = sorted(days_data.keys())
    rate = _fuel_rate()

    for date_str in sorted_dates:
        day = days_data[date_str]

        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_fmt = dt.strftime("%d.%m.%Y")

        row = [date_fmt]

        for shift in ["m", "d", "e", "x"]:
            s = day["shifts"].get(shift, {})
            row.append(_time_to_hhmm(s.get("start")))
            row.append(_time_to_hhmm(s.get("end")))

        total_day_hours = 0.0
        for shift in ["m", "d", "e", "x"]:
            s = day["shifts"].get(shift, {})
            start = s.get("start")
            end = s.get("end")
            if start and end:
                total_day_hours += (end - start).total_seconds() / 3600.0
        row.append(_hours_to_hhmm(total_day_hours))

        fuel_start = day["fuel_start"]
        row.append(f"{fuel_start:.1f}" if fuel_start != 0 else "")

        fuel_consumed = total_day_hours * rate
        row.append(f"{fuel_consumed:.1f}" if fuel_consumed != 0 else "")

        fuel_after = fuel_start - fuel_consumed
        row.append(f"{fuel_after:.1f}" if fuel_after != 0 else "")

        total_refill = sum(r[0] for r in day["refills"])
        row.append(f"{total_refill:.1f}" if total_refill != 0 else "")

        fuel_end = day["fuel_end"]
        row.append(f"{fuel_end:.1f}" if fuel_end != 0 else "")

        receipt = day["refills"][0][2] if day["refills"] else ""
        row.append(receipt or "")

        driver = day["refills"][0][1] if day["refills"] else ""
        row.append(driver or "")

        rows.append(row)

    return rows


def full_export():
    """Повний експорт з БД в Google Sheets (інкрементальний).

    Логіка:
    1. Знаходимо останню дату в Sheets
    2. Експортуємо тільки дні >= цієї дати (оновлюємо поточний + дописуємо нові)
    3. Записуємо в основну вкладку (A-Q)
    4. ПОВНІСТЮ ПЕРЕЗАПИСУЄМО вкладку LOGS_SHEET_NAME (щоб уникнути дублювання)
    """
    logger.info("📤 Починаємо експорт з БД в Sheets (інкрементальний)...")

    client = make_client()
    ss = open_spreadsheet(client)
    main_sheet = open_main_worksheet(ss)

    last_date = _find_last_date_in_sheet(main_sheet)

    days_data = _aggregate_logs_by_date(from_date=last_date)

    if not days_data:
        logger.info("ℹ️ Немає нових даних для експорту")
        return

    main_rows = _build_export_rows(days_data)

    logger.info(f"📄 Підготовлено {len(main_rows)} рядків для основної вкладки (від {last_date or 'початку'})")

    if main_rows:
        if last_date:
            all_values = main_sheet.get_all_values()
            start_row = 3

            last_date_fmt = datetime.strptime(last_date, "%Y-%m-%d").strftime("%d.%m.%Y")
            for i, row in enumerate(all_values[2:], start=3):
                if row and row[0].strip() == last_date_fmt:
                    start_row = i
                    logger.info(f"📍 Знайдено останню дату в рядку {start_row}, перезаписуємо від нього")
                    break
            else:
                start_row = len(all_values) + 1
                logger.info(f"📍 Останню дату не знайдено в таблиці, дописуємо в кінець (рядок {start_row})")
        else:
            start_row = 3

        end_row = start_row + len(main_rows) - 1
        main_sheet.update(f"A{start_row}:Q{end_row}", main_rows, value_input_option="USER_ENTERED")
        logger.info(f"✅ Основна вкладка оновлена (рядки {start_row}-{end_row})")

    logs_title = _logs_sheet_name()
    logger.info(f"📄 Експортуємо вкладку {logs_title} (повна перезапис)...")

    try:
        events_sheet = ss.worksheet(logs_title)
    except Exception:
        events_sheet = ss.add_worksheet(logs_title, rows=10000, cols=7)

    events_sheet.clear()
    events_sheet.update("A1:G1", [["Дата", "Час", "Подія", "Користувач", "Значення", "Водій", "Чек"]])

    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT event_type, timestamp, user_name, value, driver_name, receipt_number
        FROM logs
        ORDER BY timestamp ASC
    """
    )
    rows = cur.fetchall()
    conn.close()

    events = []
    for event, ts_str, user, value, driver, receipt in rows:
        dt = _parse_ts(ts_str)
        if not dt:
            continue

        events.append(
            [
                dt.strftime("%d.%m.%Y"),
                dt.strftime("%H:%M:%S"),
                event,
                user or "",
                value or "",
                driver or "",
                receipt or "",
            ]
        )

    if events:
        events_sheet.update(f"A2:G{len(events) + 1}", events, value_input_option="USER_ENTERED")
        logger.info(f"✅ Вкладка {logs_title} оновлена ({len(events)} подій)")

    logger.info("✅ Експорт завершено!")
