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


def _format_logs_header(ws):
    """Оформлення заголовка вкладки логів так само як в основних вкладках."""
    if not ws:
        return

    try:
        # 1) Формат клітинок заголовка
        ws.format(
            "A1:H1",
            {
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
                "textFormat": {"bold": True},
                # Яскраво-ніжно голубий (пастельний)
                "backgroundColor": {"red": 0.70, "green": 0.90, "blue": 1.00},
            },
        )
    except Exception:
        pass

    try:
        # 2) Висота 1-го рядка (вдвічі вище за стандарт)
        sheet_id = getattr(ws, "id", None)
        if sheet_id is None and hasattr(ws, "_properties"):
            sheet_id = ws._properties.get("sheetId")

        if sheet_id is not None:
            ws.spreadsheet.batch_update(
                {
                    "requests": [
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "ROWS",
                                    "startIndex": 0,
                                    "endIndex": 1,
                                },
                                "properties": {"pixelSize": 40},
                                "fields": "pixelSize",
                            }
                        }
                    ]
                }
            )
    except Exception:
        pass


def ensure_logs_header(ws):
    if not ws:
        return

    # Українські назви колонок
    header = [
        "ID",
        "Дата/час",
        "Тип події",
        "Користувач",
        "Літри",
        "Чек",
        "Водій",
        "Значення",
    ]

    need_update = True
    try:
        row1 = ws.row_values(1)
        if row1:
            # Якщо заголовок вже такий самий — не переписуємо, але формат все одно забезпечимо
            normalized = [str(x).strip() for x in row1[: len(header)]]
            if normalized == header:
                need_update = False
    except Exception:
        pass

    if need_update:
        try:
            ws.update(
                range_name="A1:H1",
                values=[header],
                value_input_option="RAW",
            )
        except Exception:
            pass

    _format_logs_header(ws)


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
        value_input_option="USER_ENTERED",
    )
