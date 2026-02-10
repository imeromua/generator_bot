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


# For collecting all shifts, but report only shows first 2 intervals
_SHIFT_ORDER = ["m", "d", "e", "x"]


def _month_range_kyiv(period: str) -> tuple[str, str, str]:
    """Return (start_date, end_date, label) for current/prev month in Kyiv tz."""
    now = datetime.now(config.KYIV)

    if period == "current":
        start = now.replace(day=1).date()
        if start.month == 12:
            next_m = date(start.year + 1, 1, 1)
        else:
            next_m = date(start.year, start.month + 1, 1)
        end = next_m - timedelta(days=1)
        label = _UA_MONTHS.get(start.month, str(start.month))
        return start.isoformat(), end.isoformat(), label

    first_day_current = now.replace(day=1).date()
    end = first_day_current - timedelta(days=1)
    start = end.replace(day=1)
    label = _UA_MONTHS.get(start.month, str(start.month))
    return start.isoformat(), end.isoformat(), label


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=config.KYIV)
    except Exception:
        return None


def _fmt_hhmm(dt: datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else ""


def _hours_between(a: datetime | None, b: datetime | None) -> float:
    if not a or not b:
        return 0.0
    sec = (b - a).total_seconds()
    if sec < 0:
        return 0.0
    return sec / 3600.0


async def generate_report(period: str):
    """Generate Excel report from DB (month layout + 'ПОДІЇ') with formulas.

    The sample sheet uses formulas for:
    - total hours (shown as ВІДПРАЦЬОВАНО, Г)
    - fuel spent
    - balances (morning/after/evening)

    Shows only 2 shift intervals per day (matching template).
    Removed: НОМЕР ЧЕКА, ВОДІЙ, ВІДПОВІДАЛЬНИЙ columns.

    period: 'current' or 'prev'
    """
    try:
        start_date, end_date, month_label = _month_range_kyv(period) if False else _month_range_kyiv(period)
        logs = db.get_logs_for_period(start_date, end_date)

        try:
            fuel_rate = float(getattr(config, "FUEL_CONSUMPTION", 5.3) or 5.3)
            if fuel_rate <= 0:
                fuel_rate = 5.3
        except Exception:
            fuel_rate = 5.3

        # Build per-day structure (collect all shifts, but display only first 2 intervals)
        days: dict[str, dict] = {}
        refills_by_day: dict[str, list] = {}

        for (event_type, ts, user_name, value, driver_name, receipt_number) in logs:
            dt = _parse_ts(ts)
            if not dt:
                continue
            day_key = dt.strftime("%d.%m.%Y")
            day_iso = dt.strftime("%Y-%m-%d")

            if day_key not in days:
                days[day_key] = {"shifts": {c: {"start": None, "end": None} for c in _SHIFT_ORDER}}

            if event_type in ("m_start", "d_start", "e_start", "x_start"):
                c = event_type.split("_", 1)[0]
                days[day_key]["shifts"][c]["start"] = dt
                continue

            if event_type in ("m_end", "d_end", "e_end", "x_end"):
                c = event_type.split("_", 1)[0]
                days[day_key]["shifts"][c]["end"] = dt
                continue

            if event_type == "refill":
                try:
                    liters = float(str(value or "0").replace(",", "."))
                except Exception:
                    liters = 0.0
                refills_by_day.setdefault(day_iso, []).append({"liters": liters})

        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = month_label

        # Column map (1-based) - matching template with 2 shifts only
        COL_DATE = 1
        COL_S1_START, COL_S1_END = 2, 3
        COL_S2_START, COL_S2_END = 4, 5
        COL_TOTAL_HOURS = 6           # ВІДПРАЦЬОВАНО, Г
        COL_FUEL_MORNING = 7          # ЗАЛИШОК ПАЛИВА НА РАНОК
        COL_FUEL_SPENT = 8            # ВИТРАТИ ПАЛИВА
        COL_FUEL_LEFT = 9             # ЗАЛИШОК
        COL_REFILL = 10               # ЗАПРВКА
        COL_FUEL_EVENING = 11         # ЗАЛИШОК ПАЛИВА ВЕЧІР
        COL_FUEL_RATE = 12            # fuel rate (л/год)

        headers = [
            "ДАТА",
            "ПОЧАТОК, Г", "КІНЕЦЬ, Г",
            "ПОЧАТОК, Г", "КІНЕЦЬ, Г",
            "ВІДПРАЦЬОВАНО, Г",
            "ЗАЛИШОК ПАЛИВА НА РАНОК",
            "ВИТРАТИ ПАЛИВА",
            "ЗАЛИШОК",
            "ЗАПРВКА",
            "ЗАЛИШОК ПАЛИВА ВЕЧІР",
            fuel_rate,
        ]
        ws.append(headers)

        fill = PatternFill("solid", fgColor="1F4E79")
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # Sort days by date
        def _key(dstr: str):
            try:
                return datetime.strptime(dstr, "%d.%m.%Y")
            except Exception:
                return datetime.max

        first_row = 2
        row_idx = first_row

        for day_key in sorted(days.keys(), key=_key):
            shifts = days[day_key]["shifts"]
            
            # Collect all shift intervals and pick first 2 that exist
            intervals_found = []
            for c in _SHIFT_ORDER:
                if shifts[c]["start"] or shifts[c]["end"]:
                    intervals_found.append((shifts[c]["start"], shifts[c]["end"]))
            
            # Fill first 2 intervals (or blank if less)
            i1_start = _fmt_hhmm(intervals_found[0][0]) if len(intervals_found) > 0 else ""
            i1_end = _fmt_hhmm(intervals_found[0][1]) if len(intervals_found) > 0 else ""
            i2_start = _fmt_hhmm(intervals_found[1][0]) if len(intervals_found) > 1 else ""
            i2_end = _fmt_hhmm(intervals_found[1][1]) if len(intervals_found) > 1 else ""

            day_iso = datetime.strptime(day_key, "%d.%m.%Y").strftime("%Y-%m-%d")
            refills = refills_by_day.get(day_iso, [])
            refill_liters = sum(r.get("liters", 0.0) for r in refills)

            ws.append([
                day_key,
                i1_start, i1_end,
                i2_start, i2_end,
                None,  # total hours formula
                None,  # morning fuel formula (except first row)
                None,  # fuel spent formula
                None,  # fuel left formula
                round(refill_liters, 1) if refill_liters else "",
                None,  # evening fuel formula
                fuel_rate,
            ])

            # Formulas
            r = row_idx
            def c(col: int) -> str:
                from openpyxl.utils import get_column_letter
                return f"{get_column_letter(col)}{r}"

            # Total hours = sum of 2 intervals
            # Each interval: IF(OR(start="",end=""),0,end-start)
            intervals = [(COL_S1_START, COL_S1_END), (COL_S2_START, COL_S2_END)]
            parts = []
            for s_col, e_col in intervals:
                parts.append(f"IF(OR({c(s_col)}=\"\",{c(e_col)}=\"\"),0,{c(e_col)}-{c(s_col)})")
            ws.cell(row=r, column=COL_TOTAL_HOURS).value = "=" + "+".join(parts)
            ws.cell(row=r, column=COL_TOTAL_HOURS).number_format = "[h]:mm:ss"

            # Fuel spent = total_hours*24 * fuel_rate
            ws.cell(row=r, column=COL_FUEL_SPENT).value = f"={c(COL_TOTAL_HOURS)}*24*{c(COL_FUEL_RATE)}"

            # Morning fuel: first row blank, others = prev evening
            if r == first_row:
                ws.cell(row=r, column=COL_FUEL_MORNING).value = ""
            else:
                ws.cell(row=r, column=COL_FUEL_MORNING).value = f"={c(COL_FUEL_EVENING).replace(str(r), str(r-1))}"

            # Fuel left = morning - spent
            ws.cell(row=r, column=COL_FUEL_LEFT).value = f"=IF({c(COL_FUEL_MORNING)}=\"\",\"\",{c(COL_FUEL_MORNING)}-{c(COL_FUEL_SPENT)})"

            # Evening = left + refill
            ws.cell(row=r, column=COL_FUEL_EVENING).value = f"=IF({c(COL_FUEL_LEFT)}=\"\",\"\",{c(COL_FUEL_LEFT)}+{c(COL_REFILL)})"

            row_idx += 1

        # autosize
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                if cell.value is None:
                    continue
                max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = min(max_len + 2, 38)

        # Raw events sheet
        ws2 = wb.create_sheet("ПОДІЇ")
        ws2.append(["ID", "Дата/час", "Тип події", "Користувач", "Літри", "Чек", "Водій", "Значення"])
        for (event_type, ts, user_name, value, driver_name, receipt_number) in logs:
            liters_col = value if event_type == "refill" else ""
            ws2.append(["", ts, event_type, user_name, liters_col, receipt_number, driver_name, value])

        for cell in ws2[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")

        ts = datetime.now(config.KYIV).strftime("%Y%m%d_%H%M%S")
        filename = f"report_{period}_{month_label}_{ts}.xlsx"
        wb.save(filename)

        caption = (
            f"📊 <b>Звіт з БД</b>\n"
            f"🗓 Період: <b>{start_date}</b> — <b>{end_date}</b>\n"
            f"📁 Файл: <code>{filename}</code>"
        )
        return filename, caption

    except Exception as e:
        logger.error(f"❌ Помилка генерації звіту: {e}", exc_info=True)
        return None, f"❌ Помилка генерації звіту: {str(e)}"
