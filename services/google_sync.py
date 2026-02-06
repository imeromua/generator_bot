import asyncio
import gspread
import logging
import os
import re
from google.oauth2.service_account import Credentials
from datetime import datetime, date, timedelta

import database.db_api as db
import database.models as db_models
import config

logging.basicConfig(level=logging.INFO)


def _sheet_name_to_month(sheet_name: str):
    if not sheet_name:
        return None
    name = sheet_name.strip().upper()
    mapping = {
        "СІЧЕНЬ": 1, "ЛЮТИЙ": 2, "БЕРЕЗЕНЬ": 3, "КВІТЕНЬ": 4, "ТРАВЕНЬ": 5, "ЧЕРВЕНЬ": 6,
        "ЛИПЕНЬ": 7, "СЕРПЕНЬ": 8, "ВЕРЕСЕНЬ": 9, "ЖОВТЕНЬ": 10, "ЛИСТОПАД": 11, "ГРУДЕНЬ": 12,
        "ЯНВАРЬ": 1, "ФЕВРАЛЬ": 2, "МАРТ": 3, "АПРЕЛЬ": 4, "МАЙ": 5, "ИЮНЬ": 6,
        "ИЮЛЬ": 7, "АВГУСТ": 8, "СЕНТЯБРЬ": 9, "ОКТЯБРЬ": 10, "НОЯБРЬ": 11, "ДЕКАБРЬ": 12,
        "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
        "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
    }
    return mapping.get(name)


def _try_parse_date_from_cell(value: str, sheet_month, sheet_year: int):
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    if s.upper() in ("ДАТА", "DATE"):
        return None

    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        pass

    try:
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", s):
            return datetime.strptime(s, "%d.%m.%Y").date()
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2}", s):
            return datetime.strptime(s, "%d.%m.%y").date()
    except Exception:
        pass

    try:
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", s):
            return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        pass

    try:
        if re.fullmatch(r"\d{1,2}\.\d{1,2}", s):
            dd, mm = s.split(".")
            return date(sheet_year, int(mm), int(dd))
    except Exception:
        pass

    try:
        s_num = s.replace(",", ".")
        if re.fullmatch(r"\d+(\.\d+)?", s_num):
            f = float(s_num)
            if f >= 30000:
                base = date(1899, 12, 30)
                return base + timedelta(days=int(f))
    except Exception:
        pass

    try:
        if re.fullmatch(r"\d{1,2}", s):
            day = int(s)
            if 1 <= day <= 31 and sheet_month:
                return date(sheet_year, sheet_month, day)
    except Exception:
        pass

    return None


def _find_row_by_date_in_column_a(sheet, target_date: date, sheet_name: str):
    col_a = sheet.col_values(1)
    sheet_month = _sheet_name_to_month(sheet_name)
    sheet_year = target_date.year

    for idx, cell_value in enumerate(col_a, start=1):
        d = _try_parse_date_from_cell(cell_value, sheet_month=sheet_month, sheet_year=sheet_year)
        if d == target_date:
            return idx

    return None


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
    """На кожній ітерації підтягуємо еталонні значення з таблиці в БД (але НЕ пишемо назад у Sheet)."""
    try:
        today = datetime.now(config.KYIV).date()
        today_str = today.strftime("%Y-%m-%d")

        row = _find_row_by_date_in_column_a(sheet, today, config.SHEET_NAME)
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


def _import_initial_state_from_sheet(sheet):
    """Одноразовий імпорт (fallback) стартових значень на сьогодні."""
    try:
        today = datetime.now(config.KYIV).date()
        today_str = today.strftime("%Y-%m-%d")

        row = _find_row_by_date_in_column_a(sheet, today, config.SHEET_NAME)
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
                    logging.info(f"✅ Імпорт стартового палива з таблиці: {fuel_val}л (рядок {row})")

        if moto_val is not None:
            try:
                cur_total = float(state.get("total_hours", 0.0) or 0.0)
            except Exception:
                cur_total = 0.0

            if cur_total <= 0.0 or (moto_val > (cur_total + 0.05)):
                db.set_total_hours(moto_val)
                logging.info(f"✅ Імпорт мотогодин з таблиці: {moto_val:.2f} год (рядок {row})")

    except Exception as e:
        logging.error(f"❌ Помилка імпорту стартових значень: {e}", exc_info=True)


async def sync_loop():
    """Фоновий процес синхронізації"""
    if not config.SHEET_ID:
        logging.error("❌ SHEET_ID не знайдено! Синхронізацію вимкнено.")
        return

    if not os.path.exists("service_account.json"):
        logging.error("❌ Файл service_account.json не знайдено! Синхронізацію вимкнено.")
        return

    print(f"🚀 Google Sync запущено. Таблиця: {config.SHEET_NAME}")

    while True:
        try:
            scopes = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
            client = gspread.authorize(creds)

            sheet = client.open_by_key(config.SHEET_ID).worksheet(config.SHEET_NAME)

            # --- ЕТАП 0: СТАРТОВІ ЗНАЧЕННЯ (fallback) ---
            _import_initial_state_from_sheet(sheet)

            # --- ЕТАП 0.1: CANONICAL SYNC (таблиця -> БД) ---
            _sync_canonical_state_from_sheet(sheet)

            # --- ЕТАП 1: ЧИТАННЯ (Синхронізація водіїв) ---
            try:
                drivers_raw = sheet.col_values(28)[2:]
                drivers_clean = [d.strip() for d in drivers_raw if d.strip()]

                if drivers_clean:
                    db.sync_drivers_from_sheet(drivers_clean)
                    logging.info(f"✅ Синхронізовано {len(drivers_clean)} водіїв")
            except Exception as e:
                logging.error(f"⚠️ Не вдалося прочитати список водіїв: {e}")

            # --- ЕТАП 2: ЗАПИС ---
            # Таблиця = еталон по паливу/мотогодинах. Заправки НЕ пишемо в таблицю.
            logs = db.get_unsynced()
            if logs:
                ids_to_mark = []

                for l in logs:
                    lid, ltype, ltime, luser, lval, ldriver, _ = l

                    # refuel: залишаємо тільки в БД як журнал, в Google Sheet не записуємо
                    if ltype == "refill":
                        ids_to_mark.append(lid)
                        continue

                    # інші події (старт/стоп змін) — як і раніше можна синхронізувати в Sheet
                    # (якщо захочеш — можу зробити окремий перемикач у config)
                    try:
                        log_date_str = ltime.split(" ")[0]
                        log_time_hhmm = ltime.split(" ")[1][:5]
                    except Exception:
                        continue

                    try:
                        log_date_obj = datetime.strptime(log_date_str, "%Y-%m-%d").date()
                    except Exception:
                        continue

                    r = _find_row_by_date_in_column_a(sheet, log_date_obj, config.SHEET_NAME)
                    if not r:
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

                    elif ltype == "auto_close":
                        col = 7
                        user_col = 24

                    if col:
                        try:
                            sheet.update(
                                range_name=f"{gspread.utils.rowcol_to_a1(r, col)}",
                                values=[[log_time_hhmm]],
                                value_input_option='USER_ENTERED'
                            )

                            if user_col and luser:
                                sheet.update(
                                    range_name=f"{gspread.utils.rowcol_to_a1(r, user_col)}",
                                    values=[[luser]],
                                    value_input_option='RAW'
                                )

                            ids_to_mark.append(lid)
                        except Exception:
                            pass

                if ids_to_mark:
                    db.mark_synced(ids_to_mark)

        except gspread.exceptions.APIError as e:
            logging.error(f"❌ Google API Error: {e}")
        except gspread.exceptions.SpreadsheetNotFound:
            logging.error(f"❌ Таблиця з ID {config.SHEET_ID} не знайдена!")
        except Exception as e:
            logging.error(f"❌ Sync Error: {e}")

        await asyncio.sleep(60)
