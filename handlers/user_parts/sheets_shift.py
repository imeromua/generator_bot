"""Google Sheets shift synchronization.

Bidirectional sync with Google Sheets for shift tracking.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

import config
import database.db_api as db
from database.models import get_connection, begin_transaction
from utils.time import now_kiev
from utils.sheets_dates import find_row_by_date_in_column_a
from utils.sheets_guard import sheets_forced_offline


_SHIFT_COLS = {
    "m": (2, 3),
    "d": (4, 5),
    "e": (6, 7),
    "x": (8, 9),
}


def shift_pretty(code_or_event: str) -> str:
    """Перетворює технічний код зміни у користувацьку назву з емодзі часу доби.

    Args:
        code_or_event: код зміни (m/d/e/x) або повна подія (m_start/d_end/тощо)

    Returns:
        Назва зміни з емодзі (наприклад "🌅 Зміна 1")

    Examples:
        >>> shift_pretty("m")
        "🌅 Зміна 1"
        >>> shift_pretty("m_start")
        "🌅 Зміна 1"
        >>> shift_pretty("d")
        "☀️ Зміна 2"
    """
    code = code_or_event
    if "_" in code_or_event:
        code = code_or_event.split("_", 1)[0]

    # Емодзі часу доби для кращого відображення на всіх платформах
    return {
        "m": "🌅 Зміна 1",  # Ранок (morning)
        "d": "☀️ Зміна 2",  # День (day)
        "e": "🌙 Зміна 3",  # Вечір (evening)
        "x": "⚡ Екстра",   # Екстра зміна
    }.get(code, code_or_event)


def shift_prev_required(code: str) -> Optional[str]:
    """Get required previous shift code.

    Args:
        code: Shift code (m/d/e/x)

    Returns:
        Previous shift code or None
    """
    return {
        "d": "m",
        "e": "d",
    }.get(code)


def open_ws_sync() -> Optional[gspread.Worksheet]:
    """Open Google Sheets worksheet for sync.

    Returns:
        Worksheet object or None if unavailable
    """
    if sheets_forced_offline():
        return None

    if not config.SHEET_ID:
        return None
    
    # FIX #26: Use configurable service account path
    service_account_path = getattr(config, 'SERVICE_ACCOUNT_PATH', 'service_account.json')
    if not os.path.exists(service_account_path):
        return None

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(service_account_path, scopes=scopes)
    client = gspread.authorize(creds)
    ss = client.open_by_key(config.SHEET_ID)
    return ss.worksheet(config.SHEET_NAME)


def get_sheet_shift_info_sync() -> tuple[bool, Optional[str], set, dict]:
    """Повертає (sheet_ok, open_shift_code|None, completed_set, start_time_by_shift).

    Returns:
        Tuple of:
        - sheet_ok: Whether sheet access succeeded
        - open_shift_code: Currently open shift or None
        - completed_set: Set of completed shift codes
        - start_time_by_shift: Dict of shift code -> start time
    """
    ws = open_ws_sync()
    if not ws:
        return False, None, set(), {}

    today = now_kiev().date()
    row = find_row_by_date_in_column_a(ws, today, config.SHEET_NAME)
    if not row:
        return False, None, set(), {}

    rng = ws.get(f"A{row}:I{row}")
    vals = (rng[0] if rng else [])

    def cell(col: int) -> str:
        idx = col - 1
        if idx < 0:
            return ""
        if idx >= len(vals):
            return ""
        v = vals[idx]
        if v is None:
            return ""
        return str(v).strip()

    completed = set()
    start_times = {}
    open_shift = None

    for code, (c_start, c_end) in _SHIFT_COLS.items():
        s = cell(c_start)
        e = cell(c_end)
        if e:
            completed.add(code)
        if s:
            start_times[code] = s
        if s and not e and open_shift is None:
            open_shift = code

    return True, open_shift, completed, start_times


def sync_db_from_sheet_open_shift(open_shift_code: str, start_times: dict) -> None:
    """Якщо таблиця показує відкриту зміну — синхронізуємо мінімальний стан в БД для блокування.
    
    FIX #25: Now uses transaction to ensure atomicity of all state updates.

    Args:
        open_shift_code: Shift code that is open
        start_times: Dict of shift code -> start time string
    """
    conn = None
    try:
        conn = get_connection()
        begin_transaction(conn)
        
        # Update all state values atomically
        from database.api.state import _conn_set_state_value
        
        _conn_set_state_value(conn, "status", "ON")
        _conn_set_state_value(conn, "active_shift", f"{open_shift_code}_start")

        st_time = (start_times.get(open_shift_code, "") or "").strip()
        if st_time:
            hhmm = st_time[:5]
            _conn_set_state_value(conn, "last_start_time", hhmm)

            # Якщо зараз після півночі, а старт був "вчора ввечері" — ставимо дату вчора.
            try:
                start_t = datetime.strptime(hhmm, "%H:%M").time()
                now = now_kiev()
                start_date = now.date()
                if now.time() < start_t:
                    start_date = start_date - timedelta(days=1)
                _conn_set_state_value(conn, "last_start_date", start_date.strftime("%Y-%m-%d"))
            except Exception:
                _conn_set_state_value(conn, "last_start_date", now_kiev().strftime("%Y-%m-%d"))
        
        conn.commit()

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        import logging
        logging.error(f"❌ Failed to sync DB from Sheet: {e}", exc_info=True)
        
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
