import logging

from gspread.utils import rowcol_to_a1

import database.db_api as db


def parse_refill_value(value_raw: str | None) -> tuple[float, str]:
    liters = 0.0
    receipt = ""

    if not value_raw:
        return liters, receipt

    s = str(value_raw).strip()
    if not s:
        return liters, receipt

    if "|" in s:
        a, b = s.split("|", 1)
        s_l = a.strip()
        receipt = b.strip()
    else:
        s_l = s

    try:
        liters = float(s_l.replace(",", "."))
    except Exception:
        liters = 0.0

    return liters, receipt


def update_refill_aggregates_for_date(sheet, row: int, date_str: str):
    """Idempotent update: агрегуємо заправки з БД, а не додаємо до поточного значення в Sheet."""
    refills = db.get_refills_for_date(date_str)

    total_liters = 0.0
    receipts = []
    drivers = []

    for ts, user_name, value, driver_name in refills:
        l, r = parse_refill_value(value)
        total_liters += float(l or 0.0)
        if r and r not in receipts:
            receipts.append(r)
        if driver_name:
            d = str(driver_name).strip()
            if d and d not in drivers:
                drivers.append(d)

    # N(14): Привезено палива (сума)
    try:
        sheet.update(
            range_name=rowcol_to_a1(row, 14),
            values=[[str(round(total_liters, 2)).replace(".", ",")]],
            value_input_option='USER_ENTERED'
        )
    except Exception as e:
        logging.error(f"❌ Refill total update error date={date_str}: {e}")

    # P(16): Номер чека (всі через кому)
    try:
        sheet.update(
            range_name=rowcol_to_a1(row, 16),
            values=[[", ".join(receipts)]],
            value_input_option='USER_ENTERED'
        )
    except Exception as e:
        logging.error(f"❌ Refill receipt update error date={date_str}: {e}")

    # AA(27): водії/хто привіз (через кому)
    try:
        sheet.update(
            range_name=rowcol_to_a1(row, 27),
            values=[[", ".join(drivers)]],
            value_input_option='USER_ENTERED'
        )
    except Exception as e:
        logging.error(f"❌ Refill drivers update error date={date_str}: {e}")
