import config

from .refill import parse_refill_value


def ensure_logs_worksheet(ss):
    """Повертає worksheet для журналу подій. Якщо не існує — створює."""
    title = (getattr(config, "LOGS_SHEET_NAME", None) or "ПОДІЇ").strip()
    try:
        return ss.worksheet(title)
    except Exception:
        try:
            return ss.add_worksheet(title=title, rows=5000, cols=10)
        except Exception:
            # якщо не можемо створити — просто не будемо вести журнал
            return None


def ensure_logs_header(ws):
    if not ws:
        return
    header = ["log_id", "timestamp", "event_type", "user_name", "liters", "receipt", "driver", "value_raw"]
    try:
        row1 = ws.row_values(1)
        if row1 and (row1[0].strip().lower() == "log_id"):
            return
    except Exception:
        pass

    try:
        ws.update(
            range_name="A1:H1",
            values=[header],
            value_input_option="RAW"
        )
    except Exception:
        pass


def ensure_logs_rows(ws, needed_row: int):
    """Гарантує, що worksheet має мінімум needed_row рядків."""
    if not ws:
        return

    try:
        current_rows = int(getattr(ws, "row_count", 0) or 0)
    except Exception:
        current_rows = 0

    if current_rows >= needed_row:
        return

    new_rows = max(needed_row, current_rows + 500)
    try:
        ws.resize(rows=new_rows)
    except Exception:
        pass


def logs_row_for_id(log_id: int) -> int:
    """1-й рядок = заголовок, дані починаються з 2-го. log_id=1 -> row=2."""
    try:
        lid = int(log_id)
    except Exception:
        lid = 0
    return max(2, lid + 1)


def upsert_log_row(ws, lid: int, ltime: str, ltype: str, luser: str, lval: str, ldriver: str):
    """Idempotent write у вкладку логів: один log_id = один рядок."""
    if not ws:
        return

    row = logs_row_for_id(lid)
    ensure_logs_rows(ws, row)

    liters = 0.0
    receipt = ""

    if (ltype or "") == "refill":
        liters, receipt = parse_refill_value(lval)

    values = [
        str(lid),
        ltime or "",
        ltype or "",
        luser or "",
        str(liters).replace(".", ",") if liters else "",
        receipt or "",
        ldriver or "",
        lval or "",
    ]

    ws.update(
        range_name=f"A{row}:H{row}",
        values=[values],
        value_input_option='USER_ENTERED'
    )
