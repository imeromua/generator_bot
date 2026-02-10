import logging
import os
from datetime import datetime, timedelta, date

import config
import database.db_api as db

logger = logging.getLogger(__name__)


_UA_MONTHS = {
    1: "СІЧЕНЬ",
    2: "ЛЮТИЙ",
    3: "БЕРЕЗЕНЬ",
    4: "КВІТЕНЬ",
    5: "ТРАВЕНЬ",
    6: "ЧЕРВЕНЬ",
    7: "ЛИПЕНЬ",
    8: "СЕРПЕНЬ",
    9: "ВЕРЕСЕНЬ",
    10: "ЖОВТЕНЬ",
    11: "ЛИСТОПАД",
    12: "ГРУДЕНЬ",
}


def _month_range_kyiv(period: str) -> tuple[str, str, str]:
    """Return (start_date, end_date, label) for current/prev month in Kyiv tz."""
    now = datetime.now(config.KYIV)

    if period == "current":
        start = now.replace(day=1).date()
        # first day of next month
        if start.month == 12:
            next_m = date(start.year + 1, 1, 1)
        else:
            next_m = date(start.year, start.month + 1, 1)
        end = next_m - timedelta(days=1)
        label = _UA_MONTHS.get(start.month, str(start.month))
        return start.isoformat(), end.isoformat(), label

    # prev
    first_day_current = now.replace(day=1).date()
    end = first_day_current - timedelta(days=1)
    start = end.replace(day=1)
    label = _UA_MONTHS.get(start.month, str(start.month))
    return start.isoformat(), end.isoformat(), label


async def generate_report(period: str):
    """Generate Excel report from the database (DB is the source of truth).

    period: 'current' or 'prev'

    Output: (file_path, caption)
    """
    try:
        start_date, end_date, month_label = _month_range_kyiv(period)

        logs = db.get_logs_for_period(start_date, end_date)

        # Minimal XLSX: one sheet with logs
        try:
            from openpyxl import Workbook
            from openpyxl.utils import get_column_letter
        except Exception as e:
            return None, f"❌ openpyxl не доступний: {e}"

        wb = Workbook()
        ws = wb.active
        ws.title = f"{month_label}"

        headers = ["event_type", "timestamp", "user_name", "value", "driver_name", "receipt_number"]
        ws.append(headers)

        for row in logs:
            # row is tuple matching headers
            ws.append(list(row))

        # simple autosize
        for col_idx, h in enumerate(headers, start=1):
            max_len = len(h)
            for cell in ws[get_column_letter(col_idx)]:
                if cell.value is None:
                    continue
                max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 50)

        ts = datetime.now(config.KYIV).strftime("%Y%m%d_%H%M%S")
        filename = f"report_{period}_{start_date}_{end_date}_{ts}.xlsx"
        wb.save(filename)

        caption = (
            f"📊 <b>Звіт з БД</b>\n"
            f"🗓 Період: <b>{start_date}</b> — <b>{end_date}</b>\n"
            f"📁 Файл: <code>{filename}</code>\n"
            f"🧾 Рядків: <b>{len(logs)}</b>"
        )
        return filename, caption

    except Exception as e:
        logger.error(f"❌ Помилка генерації звіту: {e}", exc_info=True)
        return None, f"❌ Помилка генерації звіту: {str(e)}"
