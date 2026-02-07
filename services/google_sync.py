import asyncio
import logging

import gspread

import database.db_api as db
import config

from utils.sheets_guard import sheets_forced_offline

from services.google_sync_parts.client import validate_sync_prereqs, make_client, open_spreadsheet, open_main_worksheet
from services.google_sync_parts.offline import should_skip_offline_probe
from services.google_sync_parts.canonical import sync_canonical_state_once
from services.google_sync_parts.sync_cycle import run_sync_cycle

logging.basicConfig(level=logging.INFO)


__all__ = ["sync_loop", "sync_canonical_state_once"]


async def sync_loop():
    """Фоновий процес синхронізації"""
    if not config.SHEET_ID:
        logging.error("❌ SHEET_ID не знайдено! Синхронізацію вимкнено.")
        db.sheet_mark_fail()
        db.sheet_check_offline()
        return

    if not validate_sync_prereqs():
        logging.error("❌ Файл service_account.json не знайдено! Синхронізацію вимкнено.")
        db.sheet_mark_fail()
        db.sheet_check_offline()
        return

    print(f"🚀 Google Sync запущено. Таблиця: {config.SHEET_NAME}")

    while True:
        try:
            # Примусовий OFFLINE: взагалі не ходимо в Sheets.
            try:
                if sheets_forced_offline():
                    await asyncio.sleep(60)
                    continue
            except Exception:
                pass

            # Авто OFFLINE: робимо пробу раз на N хвилин, щоб можна було відновитись.
            if should_skip_offline_probe():
                await asyncio.sleep(60)
                continue

            client = make_client()
            ss = open_spreadsheet(client)
            sheet = open_main_worksheet(ss)

            run_sync_cycle(ss, sheet)

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
