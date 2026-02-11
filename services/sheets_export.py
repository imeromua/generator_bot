"""Модуль експорту з БД в Google Sheets.

Цільова логіка (за зразком таблиці):
- Записуємо часи початку/кінця до 4 змін.
- Записуємо привезене паливо: літри (сума за день), чеки (через кому), хто привіз (через кому).
- Технічні колонки (розхід, коефіцієнти тощо) не чіпаємо.

Семантика експорту:
- Не чіпаємо попередні дні.
- Оновлюємо лише поточний день (сьогодні за київським часом) та всі наступні дні,
  якщо для них уже є логи в БД.

Колонки, які заповнюємо (інші лишаємо порожніми/як є):
- A = дата (ДД.ММ.РРРР)
- B,C,D,E,F,G,H,I = часи старт/стоп змін 1..4 (HH:MM)
- N = привезено палива за день (сума refills)
- P = номер(и) чека за день (через кому)
- Q = хто привіз паливо (імена водіїв, через кому)

Інші колонки (зокрема K,L,M,O,T,U та правіше) не змінюються цим модулем.
"""

import logging
from collections import defaultdict
from datetime import datetime

import config
from database.models import get_connection
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


_MAX_COL = 27  # A..AA (використовуємо тільки частину колонок)


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
    Використовується лише для діагностики, а не для обмеження експорту.
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
            logger.info("📋 Немає дат у колонці A, експортуємо всі дані")
            return None

        try:
            dt = datetime.strptime(last_date_str, "%d.%m.%Y")
            result = dt.strftime("%Y-%m-%d")
            logger.info(f"📅 Остання дата в Sheets (колонка A): {last_date_str} ({result})")
            return result
        except Exception as e:
            logger.warning(f"⚠️ Не вдалося розпарсити останню дату '{last_date_str}': {e}")
            return None

    except Exception as e:
        logger.error(f"❌ Помилка пошуку останньої дати: {e}")
        return None


def _aggregate_logs_by_date(from_date: str | None = None):
    """Групує логи по датах для експорту в основну вкладку.

    Якщо from_date задано, залишаються тільки дні >= from_date.
    """
    conn = get_connection()
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

        # A: дата
        row[0] = date_fmt

        # B-I: часи змін
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

        # N: total refill liters (sum)
        total_refill = sum(r[0] for r in day["refills"]) if day["refills"] else 0.0
        row[13] = f"{total_refill:.1f}" if total_refill else ""

        # P: receipts (comma separated)
        receipts = [rec for _amt, _drv, rec in day["refills"]] if day["refills"] else []
        row[15] = _unique_join(receipts)

        # Q: drivers who brought fuel (comma separated)
        drivers = [drv for _amt, drv, _rec in day["refills"]] if day["refills"] else []
        row[16] = _unique_join(drivers)

        rows.append(row)

    return rows


def full_export():
    """Інкрементальний експорт з БД в Google Sheets.

    Не чіпає попередні дні, оновлює тільки поточний день та всі наступні дні,
    для яких у БД є логи.
    """
    logger.info("📤 Починаємо експорт з БД в Sheets (інкрементальний)...")

    client = make_client()
    ss = open_spreadsheet(client)
    main_sheet = open_main_worksheet(ss)

    _ = _find_last_date_in_sheet(main_sheet)  # тільки для логів, логіку експорту не впливає

    today_str = datetime.now(config.KYIV).strftime("%Y-%m-%d")
    logger.info(f"📆 Експортуємо дані, починаючи з {today_str} (включно)")

    days_data = _aggregate_logs_by_date(from_date=today_str)

    if not days_data:
        logger.info("ℹ️ Немає нових даних для експорту (логів за сьогодні і пізніше немає)")
        return

    main_rows = _build_export_rows(days_data)
    logger.info(f"📄 Підготовлено {len(main_rows)} рядків для основної вкладки (від {today_str})")

    if main_rows:
        all_values = main_sheet.get_all_values()

        start_row = 3
        dates_in_sheet = [row[0].strip() if row else "" for row in all_values[2:]]
        if dates_in_sheet:
            # Знаходимо перший рядок з датою >= сьогоднішньої або перший порожній
            today_fmt = datetime.strptime(today_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            for i, date_cell in enumerate(dates_in_sheet, start=3):
                if not date_cell:
                    start_row = i
                    break
                try:
                    # якщо дата у форматі DD.MM.YYYY і >= сьогодні — оновлюємо з цього рядка
                    dt = datetime.strptime(date_cell, "%d.%m.%Y")
                    if dt >= datetime.strptime(today_fmt, "%d.%m.%Y"):
                        start_row = i
                        break
                except Exception:
                    continue
        else:
            start_row = 3

        end_row = start_row + len(main_rows) - 1

        # Формуємо окремі зрізи по колонках, які дозволено змінювати
        dates = [[r[0]] for r in main_rows]      # A
        times = [r[1:9] for r in main_rows]      # B..I
        col_n = [[r[13]] for r in main_rows]     # N
        col_p = [[r[15]] for r in main_rows]     # P
        col_q = [[r[16]] for r in main_rows]     # Q

        # Оновлюємо лише потрібні діапазони
        main_sheet.update(f"A{start_row}:A{end_row}", dates, value_input_option="USER_ENTERED")
        main_sheet.update(f"B{start_row}:I{end_row}", times, value_input_option="USER_ENTERED")
        main_sheet.update(f"N{start_row}:N{end_row}", col_n, value_input_option="USER_ENTERED")
        main_sheet.update(f"P{start_row}:P{end_row}", col_p, value_input_option="USER_ENTERED")
        main_sheet.update(f"Q{start_row}:Q{end_row}", col_q, value_input_option="USER_ENTERED")

        logger.info(
            "✅ Основна вкладка оновлена (рядки %s-%s; колонки A,B..I,N,P,Q)",
            start_row,
            end_row,
        )

    logger.info("✅ Експорт завершено!")
