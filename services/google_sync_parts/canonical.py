import logging
import threading
import time
from datetime import datetime

import database.db_api as db
import config

from utils.sheets_dates import find_row_by_date_in_column_a
from services.google_sync_parts.parsers import parse_float, parse_motohours_to_hours
from services.google_sync_parts.client import make_client, validate_sync_prereqs

# --- Canonical sync cache (avoid hitting Google Sheet on every dashboard open) ---
_CANONICAL_SYNC_LOCK = threading.Lock()
_LAST_CANONICAL_SYNC_TS = 0.0
_CANONICAL_SYNC_TTL_SECONDS = 30


def read_canonical_fuel_for_row(sheet, row: int) -> float | None:
    """Таблиця = еталон. Беремо паливо з найактуальнішої колонки: O(15) -> M(13) -> K(11)."""
    try:
        evening = parse_float(sheet.cell(row, 15).value)  # O
        if evening is not None:
            return evening
    except Exception:
        pass

    try:
        remaining_mid = parse_float(sheet.cell(row, 13).value)  # M
        if remaining_mid is not None:
            return remaining_mid
    except Exception:
        pass

    try:
        morning = parse_float(sheet.cell(row, 11).value)  # K
        if morning is not None:
            return morning
    except Exception:
        pass

    return None


def sync_canonical_state_from_sheet(sheet):
    """Підтягуємо еталонні значення з таблиці в БД."""
    try:
        today = datetime.now(config.KYIV).date()
        today_str = today.strftime("%Y-%m-%d")

        row = find_row_by_date_in_column_a(sheet, today, config.SHEET_NAME)
        if not row:
            logging.warning(f"⚠️ Canonical sync: дата {today_str} не знайдена в колонці A")
            return

        fuel_val = read_canonical_fuel_for_row(sheet, row)
        if fuel_val is not None:
            db.set_state("current_fuel", fuel_val)

        moto_raw = sheet.cell(row, 17).value
        moto_val = parse_motohours_to_hours(moto_raw)
        if moto_val is not None:
            db.set_total_hours(moto_val)

    except Exception as e:
        logging.error(f"❌ Помилка canonical sync: {e}", exc_info=True)


def sync_canonical_state_once():
    """Разове оновлення еталонного стану (Sheet -> БД). Викликається з /start для актуального дашборду."""
    try:
        if db.sheet_is_offline():
            return
    except Exception:
        return

    if not validate_sync_prereqs():
        db.sheet_mark_fail()
        db.sheet_check_offline()
        return

    global _LAST_CANONICAL_SYNC_TS

    now_ts = time.monotonic()
    with _CANONICAL_SYNC_LOCK:
        if (now_ts - _LAST_CANONICAL_SYNC_TS) < _CANONICAL_SYNC_TTL_SECONDS:
            return
        _LAST_CANONICAL_SYNC_TS = now_ts

    try:
        client = make_client()
        sheet = client.open_by_key(config.SHEET_ID).worksheet(config.SHEET_NAME)

        db.sheet_mark_ok()
        sync_canonical_state_from_sheet(sheet)

    except Exception as e:
        with _CANONICAL_SYNC_LOCK:
            _LAST_CANONICAL_SYNC_TS = 0.0
        db.sheet_mark_fail()
        db.sheet_check_offline()
        logging.error(f"❌ sync_canonical_state_once error: {e}")
