"""Модуль експорту з БД в Google Sheets.

Цільова логіка (за зразком таблиці):
- Записуємо часи початку/кінця змін.
- Записуємо привезене паливо: літри (сума за день), чеки (через кому), хто привіз (через кому).
- Записуємо відповідальних за старт/стоп по кожній зміні.

Колонки, які заповнюємо (інші лишаємо порожніми):
- B,C,D,E,F,G,H,I = часи старт/стоп змін 1..4 (HH:MM)
- N = привезено палива за день (сума refills)
- P = номер(и) чека за день (через кому)
- S,T,U,V,W,X,Y,Z = відповідальні за старт/стоп змін 1..4
- AA = хто привіз паливо (через кому)

Технічно оновлюємо діапазон A:AA, щоб не чіпати праві колонки, якщо вони існують.
"""

import logging
from collections import defaultdict
from datetime import datetime

import config
import database.db_api as db
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


_MAX_COL = 27  # A..AA


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


def _aggregate_logs_by_date(from_date: str | None = None):
    """Групує логи по датах для експорту в основну вкладку."""
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
        }
    )

    for event, ts_str, user, value, driver, receipt in rows:
        dt = _parse_ts(ts_str)
        if not dt:
            continue

        date_str = dt.strftime("%Y-%m-%d")
        day = days[date_str]

        if event.endswith("_start"):
            shift = event.split("_")[0]
            day["shifts"][shift]["start"] = dt
            day["shifts"][shift]["start_user"] = (user or "").strip()

        elif event.endswith("_end"):
            shift = event.split("_")[0]
            day["shifts"][shift]["end"] = dt
            day["shifts"][shift]["end_user"] = (user or "").strip()

        elif event == "refill":
            try:
                amount = float(value or 0)
            except Exception:
                amount = 0.0
            day["refills"].append((amount, (driver or "").strip(), (receipt or "").strip()))

    if from_date:
        days = {d: data for d, data in days.items() if d >= from_date}

    return days


def _unique_join(items: list[str]) -> str:
    """Join unique non-empty strings, preserving order."""
    out = []
    seen = set()
    for x in items:
        x = (x or "").strip()
        if not x or x in seen:
            continue
        out.append(x)
        seen.add(x)
    return ", ".join(out)


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

        # B-I shift times
        col_time = {
            "m": (1, 2),
            "d": (3, 4),
            "e": (5, 6),
            "x": (7, 8),
        }
        for shift, (c_start, c_end) in col_time.items():
            s = day["shifts"].get(shift, {})
            row[c_start] = _time_to_hhmm(s.get("start"))
            row[c_end] = _time_to_hhmm(s.get("end"))

        # N total refill liters (sum)
        total_refill = sum(r[0] for r in day["refills"]) if day["refills"] else 0.0
        row[13] = f"{total_refill:.1f}" if total_refill else ""

        # P receipts (comma separated)
        receipts = [rec for _amt, _drv, rec in day["refills"]] if day["refills"] else []
        row[15] = _unique_join(receipts)

        # S-Z responsible start/end per shift
        col_resp = {
            "m": (18, 19),
            "d": (20, 21),
            "e": (22, 23),
            "x": (24, 25),
        }
        for shift, (c_s, c_e) in col_resp.items():
            s = day["shifts"].get(shift, {})
            row[c_s] = (s.get("start_user") or "").strip()
            row[c_e] = (s.get("end_user") or "").strip()

        # AA drivers who brought fuel (comma separated)
        drivers = [drv for _amt, drv, _rec in day["refills"]] if day["refills"] else []
        row[26] = _unique_join(drivers)

        rows.append(row)

    return rows


def full_export():
    """Інкрементальний експорт з БД в Google Sheets."""
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
