"""Date parsing utilities for Google Sheets.

Provides flexible date parsing from various cell formats.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Any, Optional
import re


def sheet_name_to_month(sheet_name: str) -> int | None:
    """Перетворює назву листа (місяць) на номер місяця.

    Підтримує UA/RU/EN назви як в старих реалізаціях.

    Args:
        sheet_name: Sheet name (month name in Ukrainian, Russian, or English)

    Returns:
        Month number (1-12) or None if not recognized
    """
    if not sheet_name:
        return None

    name = sheet_name.strip().upper()
    mapping = {
        "СІЧЕНЬ": 1, "ЛЮТИЙ": 2, "БЕРЕЗЕНЬ": 3, "КВІТЕНЬ": 4, "ТРАВЕНЬ": 5, "ЧЕРВЕНЬ": 6,
        "ЛИПЕНЬ": 7, "СЕРПЕНЬ": 8, "ВЕРЕСЕНЬ": 9, "ЖОВТЕНЬ": 10, "ЛИСТОПАД": 11, "ГРУДЕНЬ": 12,
        "ЯНВАРЬ": 1, "ФЕВРАЛЬ": 2, "МАРТ": 3, "АПРЕЛЬ": 4, "МАЙ": 5, "ИЮНЬ": 6,
        "ИЮЛЬ": 7, "АВГУСТ": 8, "СЕНТЯБРЬ": 9, "ОКТЯБРЬ": 10, "НОЯБРЬ": 11, "ДЕКАБРЬ": 12,
        "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
        "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
    }
    return mapping.get(name)


def try_parse_date_from_cell(
    value: Any,
    sheet_month: int | None,
    sheet_year: int
) -> date | None:
    """Намагається розпарсити дату з клітинки колонки A.

    Підтримує ISO, dd.mm.yyyy, dd/mm/yyyy, 'dd.mm' (з місяцем листа),
    excel serial та один день місяця.

    Args:
        value: Cell value (can be string, int, float)
        sheet_month: Month from sheet name (1-12) or None
        sheet_year: Year for parsing

    Returns:
        Parsed date or None if parsing failed
    """
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    if s.upper() in ("ДАТА", "DATE"):
        return None

    # ISO format: YYYY-MM-DD
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        pass

    # dd.mm.yyyy or dd.mm.yy
    try:
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", s):
            return datetime.strptime(s, "%d.%m.%Y").date()
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2}", s):
            return datetime.strptime(s, "%d.%m.%y").date()
    except Exception:
        pass

    # dd/mm/yyyy
    try:
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", s):
            return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        pass

    # dd.mm (with sheet month)
    try:
        if re.fullmatch(r"\d{1,2}\.\d{1,2}", s):
            dd, mm = s.split(".")
            return date(sheet_year, int(mm), int(dd))
    except Exception:
        pass

    # Excel serial number
    try:
        s_num = s.replace(",", ".")
        if re.fullmatch(r"\d+(\.\d+)?", s_num):
            f = float(s_num)
            if f >= 30000:
                base = date(1899, 12, 30)
                return base + timedelta(days=int(f))
    except Exception:
        pass

    # Single day number (with sheet month)
    try:
        if re.fullmatch(r"\d{1,2}", s):
            day = int(s)
            if 1 <= day <= 31 and sheet_month:
                return date(sheet_year, sheet_month, day)
    except Exception:
        pass

    return None


def find_row_by_date_in_column_a(
    ws: Any,
    target_date: date,
    sheet_name: str
) -> int | None:
    """Шукає рядок за датою в колонці A.

    Args:
        ws: gspread worksheet (або сумісний об'єкт з col_values(1))
        target_date: Date to find
        sheet_name: Sheet name for month extraction

    Returns:
        Row number (1-indexed) or None if not found
    """
    col_a = ws.col_values(1)
    sheet_month = sheet_name_to_month(sheet_name)
    sheet_year = target_date.year

    for idx, cell_value in enumerate(col_a, start=1):
        d = try_parse_date_from_cell(
            cell_value,
            sheet_month=sheet_month,
            sheet_year=sheet_year
        )
        if d == target_date:
            return idx

    return None
