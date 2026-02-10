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


_SHIFT_ORDER = ["m", "d", "e", "x"]


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


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=config.KYIV)
    except Exception:
        return None


def _fmt_hhmm(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%H:%M")


def _hours_between(a: datetime | None, b: datetime | None) -> float:
    if not a or not b:
        return 0.0
    sec = (b - a).total_seconds()
    if sec < 0:
        return 0.0
    return sec / 3600.0


def _fmt_duration(hours: float) -> str:
    # Excel can accept string like HH:MM:SS; keep simple.
    total_minutes = int(round(hours * 60))
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}:00"


async def generate_report(period: str):
    """Generate Excel report from DB that matches the sample Google Sheet layout.

    - One month sheet (current/prev month)
    - One sheet "ПОДІЇ" with raw events

    period: 'current' or 'prev'
    """
    try:
        start_date, end_date, month_label = _month_range_kyiv(period)
        logs = db.get_logs_for_period(start_date, end_date)

        try:
            fuel_rate = float(getattr(config, "FUEL_CONSUMPTION", 5.3) or 5.3)
        except Exception:
            fuel_rate = 5.3

        # Build per-day structure
        # day_key -> {shift_code -> {start: dt, end: dt, personnel: str}}
        days: dict[str, dict] = {}
        refills_by_day: dict[str, list] = {}

        for (event_type, ts, user_name, value, driver_name, receipt_number) in logs:
            dt = _parse_ts(ts)
            if not dt:
                continue
            day_key = dt.strftime("%d.%m.%Y")
            day_iso = dt.strftime("%Y-%m-%d")

            if day_key not in days:
                days[day_key] = {"shifts": {c: {"start": None, "end": None, "personnel": ""} for c in _SHIFT_ORDER}}

            if event_type in ("m_start", "d_start", "e_start", "x_start"):
                c = event_type.split("_", 1)[0]
                days[day_key]["shifts"][c]["start"] = dt
                days[day_key]["shifts"][c]["personnel"] = user_name or ""
                continue

            if event_type in ("m_end", "d_end", "e_end", "x_end"):
                c = event_type.split("_", 1)[0]
                days[day_key]["shifts"][c]["end"] = dt
                if user_name and not days[day_key]["shifts"][c].get("personnel"):
                    days[day_key]["shifts"][c]["personnel"] = user_name
                continue

            if event_type == "refill":
                try:
                    liters = float(str(value or "0").replace(",", "."))
                except Exception:
                    liters = 0.0
                refills_by_day.setdefault(day_iso, []).append(
                    {
                        "ts": dt,
                        "liters": liters,
                        "receipt": receipt_number or "",
                        "driver": driver_name or "",
                        "personnel": user_name or "",
                    }
                )

        # Prepare workbook
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = month_label

        # Header similar to sample (simplified)
        headers = [
            "ДАТА",
            "ПОЧАТОК, Г (1)", "КІНЕЦЬ, Г (1)",
            "ПОЧАТОК, Г (2)", "КІНЕЦЬ, Г (2)",
            "ПОЧАТОК, Г (3)", "КІНЕЦЬ, Г (3)",
            "ПОЧАТОК, Г (4)", "КІНЕЦЬ, Г (4)",
            "ВСЬОГО ГОДИН",
            "ЗАЛИШОК ПАЛИВА НА РАНОК",
            "ВИТРАТИ ПАЛИВА",
            "ЗАЛИШОК",
            "ПРИВЕЗЕНО ПАЛИВА",
            "ЗАЛИШОК ПАЛИВА ВЕЧІР",
            "НОМЕР ЧЕКА",
            "ВОДІЙ",
            "ВІДПОВІДАЛЬНИЙ",
            str(fuel_rate),
        ]
        ws.append(headers)

        # style header
        fill = PatternFill("solid", fgColor="1F4E79")
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # Daily rows
        running_fuel = None  # unknown without explicit opening balance; keep blank until first refill? sample uses filled value.

        # Sort days by date
        def _key(dstr: str):
            try:
                return datetime.strptime(dstr, "%d.%m.%Y")
            except Exception:
                return datetime.max

        for day_key in sorted(days.keys(), key=_key):
            shifts = days[day_key]["shifts"]

            starts = [_fmt_hhmm(shifts[c]["start"]) for c in _SHIFT_ORDER]
            ends = [_fmt_hhmm(shifts[c]["end"]) for c in _SHIFT_ORDER]

            total_h = sum(_hours_between(shifts[c]["start"], shifts[c]["end"]) for c in _SHIFT_ORDER)
            fuel_used = total_h * fuel_rate

            # refills for this day (sum liters, concat receipt/driver/personnel)
            day_iso = datetime.strptime(day_key, "%d.%m.%Y").strftime("%Y-%m-%d")
            refills = refills_by_day.get(day_iso, [])
            refill_liters = sum(r.get("liters", 0.0) for r in refills)
            receipt = ", ".join([r.get("receipt", "") for r in refills if r.get("receipt")])
            driver = ", ".join([r.get("driver", "") for r in refills if r.get("driver")])
            personnel = ", ".join(sorted({r.get("personnel", "") for r in refills if r.get("personnel")}))
            if not personnel:
                # fallback: from shifts
                personnel = ", ".join(sorted({shifts[c].get("personnel", "") for c in _SHIFT_ORDER if shifts[c].get("personnel")}))

            # Fuel balance columns: we can only produce relative balances; leave morning/evening blank if unknown.
            morning_fuel = "" if running_fuel is None else round(running_fuel, 1)
            after_use = "" if running_fuel is None else round(running_fuel - fuel_used, 1)
            evening_fuel = ""
            if running_fuel is not None:
                evening_fuel = round((running_fuel - fuel_used) + refill_liters, 1)
                running_fuel = float(evening_fuel)
            elif refill_liters:
                # initialize from first refill day as baseline
                running_fuel = float(refill_liters)
                evening_fuel = round(running_fuel, 1)

            row = [
                day_key,
                starts[0], ends[0],
                starts[1], ends[1],
                starts[2], ends[2],
                starts[3], ends[3],
                _fmt_duration(total_h),
                morning_fuel,
                round(fuel_used, 1) if total_h else 0,
                after_use,
                round(refill_liters, 1) if refill_liters else "",
                evening_fuel,
                receipt,
                driver,
                personnel,
                fuel_rate,
            ]
            ws.append(row)

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

        # We don't have ID in get_logs_for_period output; keep blank.
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
