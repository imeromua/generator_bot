import logging
from datetime import datetime

from gspread.utils import rowcol_to_a1

import database.db_api as db
import config

from utils.sheets_dates import find_row_by_date_in_column_a
from services.google_sync_parts.canonical import sync_canonical_state_from_sheet
from services.google_sync_parts.initial_import import import_initial_state_from_sheet
from services.sheets_sync.logs_tab import ensure_logs_worksheet, ensure_logs_header, upsert_log_row
from services.sheets_sync.refill import update_refill_aggregates_for_date


def sync_drivers_from_sheet(sheet):
    # --- ВОДІЇ з таблиці (AB=28) ---
    try:
        drivers_raw = sheet.col_values(28)[2:]
        drivers_clean = [d.strip() for d in drivers_raw if d.strip()]
        if drivers_clean:
            db.sync_drivers_from_sheet(drivers_clean)
    except Exception as e:
        logging.error(f"⚠️ Не вдалося прочитати список водіїв: {e}")


def sync_personnel_from_sheet(sheet):
    # --- ПЕРСОНАЛ з таблиці (AC=29) ---
    try:
        personnel_raw = sheet.col_values(29)[2:]
        personnel_clean = [p.strip() for p in personnel_raw if p.strip()]
        if personnel_clean:
            db.sync_personnel_from_sheet(personnel_clean)
    except Exception as e:
        logging.error(f"⚠️ Не вдалося прочитати список персоналу: {e}")


def process_unsynced_logs(sheet, ss):
    logs_ws = ensure_logs_worksheet(ss)
    ensure_logs_header(logs_ws)

    logs = db.get_unsynced()
    if not logs:
        # canonical sync все одно робимо після циклу
        return

    ids_to_mark = []
    date_row_cache = {}

    for l in logs:
        lid, ltype, ltime, luser, lval, ldriver, _ = l

        try:
            log_date_str = (ltime or "").split(" ")[0]
            log_time_hhmm = (ltime or "").split(" ")[1][:5]
        except Exception:
            log_date_str = ""
            log_time_hhmm = ""

        # 1) Запис у ОКРЕМУ вкладку журналу — idempotent
        if logs_ws:
            try:
                upsert_log_row(
                    logs_ws,
                    lid,
                    ltime or "",
                    ltype or "",
                    luser or "",
                    lval or "",
                    ldriver or "",
                )
            except Exception as e:
                logging.error(f"❌ Logs-tab upsert error lid={lid}: {e}")
                continue

        # 2) Оновлення ОСНОВНОЇ вкладки (як було), але refill робимо idempotent
        if log_date_str:
            try:
                log_date_obj = datetime.strptime(log_date_str, "%Y-%m-%d").date()
            except Exception:
                log_date_obj = None

            if log_date_obj is not None:
                if log_date_str not in date_row_cache:
                    date_row_cache[log_date_str] = find_row_by_date_in_column_a(
                        sheet,
                        log_date_obj,
                        config.SHEET_NAME,
                    )

                r = date_row_cache.get(log_date_str)

                # REFILL: агрегуємо (може бути декілька заправок)
                if ltype == "refill":
                    try:
                        if r:
                            update_refill_aggregates_for_date(sheet, r, log_date_str)
                        ids_to_mark.append(lid)
                    except Exception as e:
                        logging.error(f"❌ Refill sync error lid={lid}: {e}")
                    continue

                col = None
                user_col = None

                if ltype == "m_start":
                    col = 2
                    user_col = 19
                elif ltype == "m_end":
                    col = 3
                    user_col = 20
                elif ltype == "d_start":
                    col = 4
                    user_col = 21
                elif ltype == "d_end":
                    col = 5
                    user_col = 22
                elif ltype == "e_start":
                    col = 6
                    user_col = 23
                elif ltype == "e_end":
                    col = 7
                    user_col = 24
                elif ltype == "x_start":
                    col = 8
                    user_col = 25
                elif ltype == "x_end":
                    col = 9
                    user_col = 26

                if col and r:
                    try:
                        sheet.update(
                            range_name=rowcol_to_a1(r, col),
                            values=[[log_time_hhmm]],
                            value_input_option="USER_ENTERED",
                        )

                        if user_col and luser:
                            sheet.update(
                                range_name=rowcol_to_a1(r, user_col),
                                values=[[luser]],
                                value_input_option="RAW",
                            )

                    except Exception as e:
                        logging.error(f"❌ Event sync error lid={lid}: {e}")

                ids_to_mark.append(lid)

        else:
            ids_to_mark.append(lid)

    if ids_to_mark:
        db.mark_synced(ids_to_mark)


def run_sync_cycle(ss, sheet):
    """Один цикл синхронізації (без offline-guard і без sleep)."""
    db.sheet_mark_ok()

    import_initial_state_from_sheet(sheet)
    sync_drivers_from_sheet(sheet)
    sync_personnel_from_sheet(sheet)

    process_unsynced_logs(sheet, ss)

    # canonical sync робимо ПІСЛЯ записів у Sheet,
    # щоб залишок у БД одразу підтягнувся після заправки/формул.
    sync_canonical_state_from_sheet(sheet)
