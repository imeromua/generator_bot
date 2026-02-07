import asyncio
import gspread
import logging
import os
import re
import threading
import time
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials
from datetime import datetime, date, timedelta

import database.db_api as db
import database.models as db_models
import config
from utils.sheets_dates import find_row_by_date_in_column_a

logging.basicConfig(level=logging.INFO)

# --- Canonical sync cache (avoid hitting Google Sheet on every dashboard open) ---
_CANONICAL_SYNC_LOCK = threading.Lock()
_LAST_CANONICAL_SYNC_TS = 0.0
_CANONICAL_SYNC_TTL_SECONDS = 30

# --- Offline probe (avoid hammering Sheets when offline) ---
_OFFLINE_PROBE_LOCK = threading.Lock()
_LAST_OFFLINE_PROBE_TS = 0.0
_OFFLINE_PROBE_INTERVAL_SECONDS = 5 * 60



def _parse_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    s = s.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _parse_motohours_to_hours(val):
    """Парсить мотогодини з Sheet у float годин. Підтримує 'HH:MM(:SS)' та числа."""
    if val is None:
        return None

    s = str(val).strip()
    if not s:
        return None

    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 2:
                hh = int(parts[0])
                mm = int(parts[1])
                return float(hh) + (float(mm) / 60.0)
            if len(parts) == 3:
                hh = int(parts[0])
                mm = int(parts[1])
                ss = int(parts[2])
                return float(hh) + (float(mm) / 60.0) + (float(ss) / 3600.0)
        except Exception:
            return None

    f = _parse_float(s)
    if f is None:
        return None

    if 1.0 < f < 31.0 and (f * 24.0) > 100.0:
        return f * 24.0

    return f


def _db_has_logs_for_date(date_str: str) -> bool:
    try:
        with db_models.get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM logs WHERE timestamp LIKE ? LIMIT 1",
                (f"{date_str}%",)
            ).fetchone()
            return row is not None
    except Exception as e:
        logging.error(f"⚠️ Не вдалося перевірити логи за дату {date_str}: {e}")
        return False


def _read_canonical_fuel_for_row(sheet, row: int) -> float | None:
    """Таблиця = еталон. Беремо паливо з найактуальнішої колонки: O(15) -> M(13) -> K(11)."""
    try:
        evening = _parse_float(sheet.cell(row, 15).value)  # O
        if evening is not None:
            return evening
    except Exception:
        pass

    try:
        remaining_mid = _parse_float(sheet.cell(row, 13).value)  # M
        if remaining_mid is not None:
            return remaining_mid
    except Exception:
        pass

    try:
        morning = _parse_float(sheet.cell(row, 11).value)  # K
        if morning is not None:
            return morning
    except Exception:
        pass

    return None


def _sync_canonical_state_from_sheet(sheet):
    """Підтягуємо еталонні значення з таблиці в БД."""
    try:
        today = datetime.now(config.KYIV).date()
        today_str = today.strftime("%Y-%m-%d")

        row = find_row_by_date_in_column_a(sheet, today, config.SHEET_NAME)
        if not row:
            logging.warning(f"⚠️ Canonical sync: дата {today_str} не знайдена в колонці A")
            return

        fuel_val = _read_canonical_fuel_for_row(sheet, row)
        if fuel_val is not None:
            db.set_state("current_fuel", fuel_val)

        moto_raw = sheet.cell(row, 17).value
        moto_val = _parse_motohours_to_hours(moto_raw)
        if moto_val is not None:
            db.set_total_hours(moto_val)

    except Exception as e:
        logging.error(f"❌ Помилка canonical sync: {e}", exc_info=True)


def sync_canonical_state_once():
    """Разове оновлення еталонного стану (Sheet -> БД). Викликається з /start для актуального дашборду."""
    # Якщо ми вже у стійкому OFFLINE-режимі — не чіпаємо Google,
    # щоб /start і дашборд не підвисали на таймаутах.
    try:
        if db.sheet_is_offline():
            return
    except Exception:
        return

    if not config.SHEET_ID:
        db.sheet_mark_fail()
        db.sheet_check_offline()
        return
    if not os.path.exists("service_account.json"):
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
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(config.SHEET_ID).worksheet(config.SHEET_NAME)

        db.sheet_mark_ok()
        _sync_canonical_state_from_sheet(sheet)

    except Exception as e:
        # Дозволяємо швидку повторну спробу при падінні (не кешуємо помилку)
        with _CANONICAL_SYNC_LOCK:
            _LAST_CANONICAL_SYNC_TS = 0.0
        db.sheet_mark_fail()
        db.sheet_check_offline()
        logging.error(f"❌ sync_canonical_state_once error: {e}")


def _import_initial_state_from_sheet(sheet):
    """Одноразовий імпорт (fallback) стартових значень на сьогодні."""
    try:
        today = datetime.now(config.KYIV).date()
        today_str = today.strftime("%Y-%m-%d")

        row = find_row_by_date_in_column_a(sheet, today, config.SHEET_NAME)
        if not row:
            logging.warning(f"⚠️ Не можу імпортувати стартові значення: дата {today_str} не знайдена в колонці A")
            return

        fuel_raw = sheet.cell(row, 11).value
        moto_raw = sheet.cell(row, 17).value

        fuel_val = _parse_float(fuel_raw)
        moto_val = _parse_motohours_to_hours(moto_raw)

        state = db.get_state()

        if fuel_val is not None:
            try:
                cur_fuel = float(state.get("current_fuel", 0.0) or 0.0)
            except Exception:
                cur_fuel = 0.0

            if cur_fuel <= 0.0:
                if not _db_has_logs_for_date(today_str):
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


def _ensure_logs_worksheet(ss):
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


def _ensure_logs_header(ws):
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


def _ensure_logs_rows(ws, needed_row: int):
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


def _logs_row_for_id(log_id: int) -> int:
    """1-й рядок = заголовок, дані починаються з 2-го. log_id=1 -> row=2."""
    try:
        lid = int(log_id)
    except Exception:
        lid = 0
    return max(2, lid + 1)


def _upsert_log_row(ws, lid: int, ltime: str, ltype: str, luser: str, lval: str, ldriver: str):
    """Idempotent write у вкладку логів: один log_id = один рядок."""
    if not ws:
        return

    row = _logs_row_for_id(lid)
    _ensure_logs_rows(ws, row)

    liters = 0.0
    receipt = ""

    if (ltype or "") == "refill":
        liters, receipt = _parse_refill_value(lval)

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


def _parse_refill_value(value_raw: str | None) -> tuple[float, str]:
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


def _update_refill_aggregates_for_date(sheet, row: int, date_str: str):
    """Idempotent update: агрегуємо заправки з БД, а не додаємо до поточного значення в Sheet."""
    refills = db.get_refills_for_date(date_str)

    total_liters = 0.0
    receipts = []
    drivers = []

    for ts, user_name, value, driver_name in refills:
        l, r = _parse_refill_value(value)
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

    # AA(27): водії/хто привіз (через кому) — залишаємо як було в існуючому sync
    try:
        sheet.update(
            range_name=rowcol_to_a1(row, 27),
            values=[[", ".join(drivers)]],
            value_input_option='USER_ENTERED'
        )
    except Exception as e:
        logging.error(f"❌ Refill drivers update error date={date_str}: {e}")


async def sync_loop():
    """Фоновий процес синхронізації"""
    if not config.SHEET_ID:
        logging.error("❌ SHEET_ID не знайдено! Синхронізацію вимкнено.")
        db.sheet_mark_fail()
        db.sheet_check_offline()
        return

    if not os.path.exists("service_account.json"):
        logging.error("❌ Файл service_account.json не знайдено! Синхронізацію вимкнено.")
        db.sheet_mark_fail()
        db.sheet_check_offline()
        return

    print(f"🚀 Google Sync запущено. Таблиця: {config.SHEET_NAME}")

    global _LAST_OFFLINE_PROBE_TS

    while True:
        try:
            # Примусовий OFFLINE: взагалі не ходимо в Sheets.
            try:
                if db.sheet_is_forced_offline():
                    await asyncio.sleep(60)
                    continue
            except Exception:
                pass

            # Авто OFFLINE: робимо пробу раз на N хвилин, щоб можна було відновитись.
            try:
                if db.sheet_is_offline():
                    now_probe = time.monotonic()
                    with _OFFLINE_PROBE_LOCK:
                        if (now_probe - _LAST_OFFLINE_PROBE_TS) < _OFFLINE_PROBE_INTERVAL_SECONDS:
                            await asyncio.sleep(60)
                            continue
                        _LAST_OFFLINE_PROBE_TS = now_probe
            except Exception:
                pass

            scopes = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
            client = gspread.authorize(creds)

            ss = client.open_by_key(config.SHEET_ID)

            sheet = ss.worksheet(config.SHEET_NAME)
            logs_ws = _ensure_logs_worksheet(ss)
            _ensure_logs_header(logs_ws)

            db.sheet_mark_ok()

            _import_initial_state_from_sheet(sheet)

            # --- ВОДІЇ з таблиці (AB=28) ---
            try:
                drivers_raw = sheet.col_values(28)[2:]
                drivers_clean = [d.strip() for d in drivers_raw if d.strip()]
                if drivers_clean:
                    db.sync_drivers_from_sheet(drivers_clean)
            except Exception as e:
                logging.error(f"⚠️ Не вдалося прочитати список водіїв: {e}")

            # --- ПЕРСОНАЛ з таблиці (AC=29) ---
            try:
                personnel_raw = sheet.col_values(29)[2:]
                personnel_clean = [p.strip() for p in personnel_raw if p.strip()]
                if personnel_clean:
                    db.sync_personnel_from_sheet(personnel_clean)
            except Exception as e:
                logging.error(f"⚠️ Не вдалося прочитати список персоналу: {e}")

            logs = db.get_unsynced()
            if logs:
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

                    # 1) Запис у ОКРЕМУ вкладку журналу (крок 4) — idempotent
                    if logs_ws:
                        try:
                            _upsert_log_row(
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
                            # якщо не змогли записати в журнал — не позначаємо synced
                            continue

                    # 2) Оновлення ОСНОВНОЇ вкладки (як було), але refill робимо idempotent
                    if log_date_str:
                        try:
                            log_date_obj = datetime.strptime(log_date_str, "%Y-%m-%d").date()
                        except Exception:
                            log_date_obj = None

                        if log_date_obj is not None:
                            if log_date_str not in date_row_cache:
                                date_row_cache[log_date_str] = find_row_by_date_in_column_a(sheet, log_date_obj, config.SHEET_NAME)

                            r = date_row_cache.get(log_date_str)

                            # REFILL: агрегуємо (може бути декілька заправок)
                            if ltype == "refill":
                                try:
                                    if r:
                                        _update_refill_aggregates_for_date(sheet, r, log_date_str)
                                    ids_to_mark.append(lid)
                                except Exception as e:
                                    logging.error(f"❌ Refill sync error lid={lid}: {e}")
                                continue

                            # START/END: часи змін пишемо як раніше
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
                                        value_input_option='USER_ENTERED'
                                    )

                                    if user_col and luser:
                                        sheet.update(
                                            range_name=rowcol_to_a1(r, user_col),
                                            values=[[luser]],
                                            value_input_option='RAW'
                                        )

                                except Exception as e:
                                    logging.error(f"❌ Event sync error lid={lid}: {e}")

                            # навіть якщо рядок дати не знайдений — журнал подій вже записали
                            ids_to_mark.append(lid)

                    else:
                        # без дати — все одно записали у журнал
                        ids_to_mark.append(lid)

                if ids_to_mark:
                    db.mark_synced(ids_to_mark)

            # canonical sync робимо ПІСЛЯ записів у Sheet,
            # щоб залишок у БД одразу підтягнувся після заправки/формул.
            _sync_canonical_state_from_sheet(sheet)

        except gspread.exceptions.APIError as e:
            db.sheet_mark_fail()
            db.sheet_check_offline()
            logging.error(f"❌ Google API Error: {e}")
        except gspread.exceptions.SpreadsheetNotFound:
            db.sheet_mark_fail()
            db.sheet_check_offline()
            logging.error(f"❌ Таблиця з ID {config.SHEET_ID} не знайдена!")
        except Exception as e:
            db.sheet_mark_fail()
            db.sheet_check_offline()
            logging.error(f"❌ Sync Error: {e}")

        await asyncio.sleep(60)
