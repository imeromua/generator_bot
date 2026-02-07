import logging
from datetime import datetime

import database.db_api as db
import database.models as db_models
import config

from utils.sheets_dates import find_row_by_date_in_column_a
from services.google_sync_parts.parsers import parse_float, parse_motohours_to_hours


def db_has_logs_for_date(date_str: str) -> bool:
    try:
        with db_models.get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM logs WHERE timestamp LIKE ? LIMIT 1",
                (f"{date_str}%",),
            ).fetchone()
            return row is not None
    except Exception as e:
        logging.error(f"⚠️ Не вдалося перевірити логи за дату {date_str}: {e}")
        return False


def import_initial_state_from_sheet(sheet):
    """Одноразовий імпорт (fallback) стартових значень на сьогодні."""
    try:
        today = datetime.now(config.KYIV).date()
        today_str = today.strftime("%Y-%m-%d")

        row = find_row_by_date_in_column_a(sheet, today, config.SHEET_NAME)
        if not row:
            logging.warning(
                f"⚠️ Не можу імпортувати стартові значення: дата {today_str} не знайдена в колонці A"
            )
            return

        fuel_raw = sheet.cell(row, 11).value
        moto_raw = sheet.cell(row, 17).value

        fuel_val = parse_float(fuel_raw)
        moto_val = parse_motohours_to_hours(moto_raw)

        state = db.get_state()

        if fuel_val is not None:
            try:
                cur_fuel = float(state.get("current_fuel", 0.0) or 0.0)
            except Exception:
                cur_fuel = 0.0

            if cur_fuel <= 0.0:
                if not db_has_logs_for_date(today_str):
                    db.set_state("current_fuel", fuel_val)

        if moto_val is not None:
            try:
                cur_total = float(state.get("total_hours", 0.0) or 0.0)
            except Exception:
                cur_total = 0.0

            if cur_total <= 0.0 or (moto_val > (cur_total + 0.05)):
                db.set_total_hours(moto_val)

    except Exception as e:
        logging.error(f"❌ Помилка імпорту стартових значень: {e}", exc_info=True)
