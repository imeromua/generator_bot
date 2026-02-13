"""Модуль експорту з БД в Google Sheets.

Цільова логіка (за зразком таблиці):
- Записуємо часи початку/кінця до 4 змін.
- Записуємо привезене паливо: літри (сума за день), чеки (через кому), хто привіз (через кому).
- Технічні колонки (розхід, коефіцієнти тощо) не чіпаємо.

Семантика експорту:
- Не перезаписуємо дні, в яких у робочих колонках (B..I,N,P,Q) уже є дані в Sheets.
- Для інших днів, які є в логах БД, дописуємо/оновлюємо рядки.

Колонки, які заповнюємо (інші лишаємо порожніми/як є):
- A = дата (ДД.ММ.РРРР)
- B,C,D,E,F,G,H,I = часи старт/стоп змін 1..4 (HH:MM)
- N = привезено палива за день (сума refills, як число без суфіксу .0)
- P = номер(и) чека за день (через кому)
- Q = хто привіз паливо (імена водіїв, через кому)

Інші колонки (зокрема K,L,M,O,T,U та правіше) не змінюються цим модулем.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

import gspread

import config
from database.models import get_connection
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


_MAX_COL = 27  # A..AA (використовуємо тільки частину колонок)


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Парсить timestamp з БД (YYYY-MM-DD HH:MM:SS).

    Args:
        ts_str: Timestamp string from database

    Returns:
        Parsed datetime or None
    """
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _time_to_hhmm(dt: Optional[datetime]) -> str:
    """Конвертує datetime в HH:MM рядок.

    Args:
        dt: Datetime object

    Returns:
        Time string HH:MM or empty string
    """
    if not dt:
        return ""
    return dt.strftime("%H:%M")


def _aggregate_logs_by_date(from_date: Optional[str] = None) -> dict[str, dict[str, Any]]:
    """Групує логи по датах для експорту в основну вкладку.

    Якщо from_date задано, залишаються тільки дні >= from_date.

    Args:
        from_date: Optional date filter (YYYY-MM-DD)

    Returns:
        Dict with date keys, each containing shifts and refills data
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

    days: dict[str, dict[str, Any]] = defaultdict(
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

    return dict(days)


def _unique_join(items: list[str]) -> str:
    """Join unique non-empty strings, preserving order.

    Args:
        items: List of strings

    Returns:
        Comma-separated unique strings
    """
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        x = (x or "").strip()
        if not x or x in seen:
            continue
        out.append(x)
        seen.add(x)
    return ", ".join(out)


def _build_export_rows(days_data: dict[str, dict[str, Any]]) -> list[list[Any]]:
    """Будує рядки для експорту.

    Args:
        days_data: Aggregated days data

    Returns:
        List of rows, each row is a list of values
    """
    rows: list[list[Any]] = []

    for date_str in sorted(days_data.keys()):
        day = days_data[date_str]

        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_fmt = dt.strftime("%d.%m.%Y")

        # Prepare empty row A..AA
        row: list[Any] = [""] * _MAX_COL

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

        # N: total refill liters (sum) — пишемо як число (int/float), без рядка "80.0"
        total_refill = sum(r[0] for r in day["refills"]) if day["refills"] else 0.0
        if total_refill:
            if abs(total_refill - round(total_refill)) < 1e-6:
                row[13] = int(round(total_refill))
            else:
                row[13] = round(total_refill, 1)
        else:
            row[13] = ""

        # P: receipts (comma separated)
        receipts = [rec for _amt, _drv, rec in day["refills"]] if day["refills"] else []
        row[15] = _unique_join(receipts)

        # Q: drivers who brought fuel (comma separated)
        drivers = [drv for _amt, drv, _rec in day["refills"]] if day["refills"] else []
        row[16] = _unique_join(drivers)

        rows.append(row)

    return rows


def full_export() -> dict[str, list[str]]:
    """Експорт з БД в Google Sheets по днях.

    Для кожної дати з логів:
    - якщо в Sheets по цій даті вже є дані в B..I,N,P,Q — день пропускається;
    - інакше дані за день записуються (або дописуються) в основну вкладку.

    Returns:
        Dict with 'updated' and 'skipped' date lists
    """
    logger.info("📤 Починаємо експорт з БД в Sheets (only fill missing days)...")

    client = make_client()
    ss = open_spreadsheet(client)
    main_sheet = open_main_worksheet(ss)

    # Читаємо всі поточні значення основної вкладки
    all_values = main_sheet.get_all_values()

    # Будуємо мапу існуючих дат: YYYY-MM-DD -> (row_index, has_payload_in_BI_N_P_Q)
    sheet_dates: dict[str, tuple[int, bool]] = {}

    for idx, row in enumerate(all_values[2:], start=3):  # починаючи з рядка 3
        if not row or not (row[0] or "").strip():
            continue
        date_cell = (row[0] or "").strip()
        try:
            dt = datetime.strptime(date_cell, "%d.%m.%Y")
            date_iso = dt.strftime("%Y-%m-%d")
        except Exception:
            continue

        # Перевіряємо, чи вже є наші робочі дані в B..I,N,P,Q
        has_payload = False
        important_cols = [1, 2, 3, 4, 5, 6, 7, 8, 13, 15, 16]
        for col_idx in important_cols:
            if col_idx < len(row) and (row[col_idx] or "").strip():
                has_payload = True
                break

        sheet_dates[date_iso] = (idx, has_payload)

    # Агрегуємо всі логи по датах (без обмеження по today)
    days_data = _aggregate_logs_by_date(from_date=None)

    if not days_data:
        logger.info("ℹ️ Немає даних у логах для експорту")
        return {"updated": [], "skipped": []}

    updated_dates: list[str] = []
    skipped_dates: list[str] = []

    # Для зручності при додаванні нових рядків тримаємо довжину поточної таблиці
    current_rows_count = len(all_values)

    for date_str in sorted(days_data.keys()):
        day = days_data[date_str]

        # Готуємо дані рядка для цієї дати
        row_data = _build_export_rows({date_str: day})[0]

        if date_str in sheet_dates:
            row_idx, has_payload = sheet_dates[date_str]
            if has_payload:
                skipped_dates.append(date_str)
                logger.info("⏭ Пропускаємо дату %s — дані вже є в Sheets (рядок %s)", date_str, row_idx)
                continue
        else:
            # Дня з такою датою ще немає в таблиці — додаємо в кінець
            current_rows_count += 1
            row_idx = current_rows_count
            sheet_dates[date_str] = (row_idx, False)
            logger.info("➕ Додаємо новий рядок для дати %s (рядок %s)", date_str, row_idx)

        # Оновлюємо/записуємо лише дозволені колонки для цього рядка
        dates = [[row_data[0]]]          # A
        times = [row_data[1:9]]          # B..I
        col_n = [[row_data[13]]]         # N
        col_p = [[row_data[15]]]         # P
        col_q = [[row_data[16]]]         # Q

        main_sheet.update(f"A{row_idx}:A{row_idx}", dates, value_input_option="USER_ENTERED")
        main_sheet.update(f"B{row_idx}:I{row_idx}", times, value_input_option="USER_ENTERED")
        main_sheet.update(f"N{row_idx}:N{row_idx}", col_n, value_input_option="USER_ENTERED")
        main_sheet.update(f"P{row_idx}:P{row_idx}", col_p, value_input_option="USER_ENTERED")
        main_sheet.update(f"Q{row_idx}:Q{row_idx}", col_q, value_input_option="USER_ENTERED")

        updated_dates.append(date_str)
        logger.info("✅ Оновлено/записано дані для дати %s (рядок %s)", date_str, row_idx)

    logger.info(
        "✅ Експорт завершено! Оновлено днів: %s; пропущено днів (вже були в Sheets): %s",
        len(updated_dates),
        len(skipped_dates),
    )

    return {"updated": updated_dates, "skipped": skipped_dates}
