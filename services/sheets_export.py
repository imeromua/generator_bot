"""Модуль експорту з БД в Google Sheets.

Поточна бізнес-вимога для ОСНОВНОЇ вкладки:
- Записуємо лише часи початку/кінця змін, привезене паливо (сума), чеки (через кому), хто привіз (через кому).
- НЕ експортуємо відповідальних за старт/стоп.

Цільові колонки, які заповнюємо в рядку:
- B,C,D,E,F,G,H,I = часи старт/стоп змін 1..4 (HH:MM)
- N = привезено палива за день (сума refills)
- P = номер(и) чека за день (через кому)
- AA = хто привіз паливо за день (через кому)

Технічно ми оновлюємо діапазон A:AA, але заповнюємо лише потрібні колонки, решта — порожні.
"""

import logging
from collections import defaultdict
from datetime import datetime

import config
import database.db_api as db
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


_MAX_COL = 27  # A..AA


def _fuel_rate() -> float:
    """Єдине джерело правди для витрати палива (л/год)."""
    try:
        return float(getattr(config, "FUEL_CONSUMPTION", 0.0) or 0.0)
    except Exception:
        return 0.0


def _logs_sheet_name() -> str:
    """Єдине джерело правди для назви вкладки подій."""
    return (getattr(config, "LOGS_SHEET_NAME", None) or "ПОДІЇ").strip() or "ПОДІЇ"


def _parse_ts(ts_str: str) -> datetime | None:
    """Парсить timestamp з БД (YYYY-MM-DD HH:MM:SS)."""
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _time_to_hhmm(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%H:%M")


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
    """Знаходить fuel_end з дня ПЕРЕД from_date (для інкрементального перерахунку).

    Лишаємо цю логіку, бо вона не заважає, а може знадобитись для інших колонок у майбутньому.
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
            "refills": [],  # [(amount, driver, receipt), ...]
            "fuel_start": 0.0,
            "fuel_end": 0.0,
        }
    )

    rate = _fuel_rate()
    running_fuel = 0.0

    for event, ts_str, _user, value, driver, receipt in rows:
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
            day["refills"].append((amount, (driver or "").strip(), (receipt or "").strip()))

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
    rows = []

    for date_str in sorted(days_data.keys()):
        day = days_data[date_str]

        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_fmt = dt.strftime("%d.%m.%Y")

        # Prepare empty row A..AA
        row = [""] * _MAX_COL

        # A
        row[0] = date_fmt

        # B-I (shift times)
        # B,C = m start/end; D,E = d start/end; F,G = e start/end; H,I = x start/end
        col_map = {
            "m": (1, 2),
            "d": (3, 4),
            "e": (5, 6),
            "x": (7, 8),
        }
        for shift, (c_start, c_end) in col_map.items():
            s = day["shifts"].get(shift, {})
            row[c_start] = _time_to_hhmm(s.get("start"))
            row[c_end] = _time_to_hhmm(s.get("end"))

        # N (index 13) total refill
        total_refill = sum(r[0] for r in day["refills"])
        row[13] = f"{total_refill:.1f}" if total_refill else ""

        # P (index 15) receipts (comma separated, unique, keep order)
        receipts = []
        seen_r = set()
        for _amt, _drv, rec in day["refills"]:
            if rec and rec not in seen_r:
                receipts.append(rec)
                seen_r.add(rec)
        row[15] = ", ".join(receipts) if receipts else ""

        # AA (index 26) drivers who brought fuel (comma separated, unique, keep order)
        drivers = []
        seen_d = set()
        for _amt, drv, _rec in day["refills"]:
            if drv and drv not in seen_d:
                drivers.append(drv)
                seen_d.add(drv)
        row[26] = ", ".join(drivers) if drivers else ""

        rows.append(row)

    return rows


def full_export():
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
        main_sheet.update(f"A{start_row}:AA{end_row}", main_rows, value_input_option="USER_ENTERED")
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
