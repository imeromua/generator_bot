import csv
import logging
import os
from datetime import datetime, timedelta

from aiogram import Router, F, types

import config
import database.db_api as db
from keyboards.builders import admin_panel

router = Router()
logger = logging.getLogger(__name__)


# --- Legacy CSV export from SQLite (kept for fallback/debug) ---
def _export_logs_to_csv(path: str, rows) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(["timestamp", "event_type", "user_name", "value", "driver_name"])
        for event_type, ts, user_name, value, driver_name in rows:
            wr.writerow([
                ts or "",
                event_type or "",
                user_name or "",
                value or "",
                driver_name or "",
            ])


async def _handle_export_csv_from_db(cb: types.CallbackQuery, start_date: str, end_date: str):
    rows = db.get_logs_for_period(start_date, end_date)

    if not rows:
        await cb.answer("ℹ️ Немає подій за цей період", show_alert=True)
        try:
            await cb.message.edit_text("⚙️ <b>Адмін Панель</b>", reply_markup=admin_panel())
        except Exception:
            pass
        return

    ts = datetime.now(config.KYIV).strftime("%Y%m%d_%H%M%S")
    filename = f"logs_{start_date}_to_{end_date}_{ts}.csv"

    try:
        _export_logs_to_csv(filename, rows)

        caption = (
            f"📤 <b>Експорт подій (CSV)</b>\n"
            f"Період: <b>{start_date}</b> — <b>{end_date}</b>\n"
            f"Рядків: <b>{len(rows)}</b>"
        )

        nav_kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="⚙️ Адмін панель", callback_data="admin_home"),
                types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home"),
            ]
        ])

        await cb.message.answer_document(types.FSInputFile(filename), caption=caption, reply_markup=nav_kb)

        await cb.answer("✅ Готово", show_alert=True)

    except Exception as e:
        logger.error(f"CSV export error: {e}", exc_info=True)
        await cb.answer("❌ Помилка експорту", show_alert=True)

    finally:
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except Exception:
            pass

        # Повертаємося в адмінку
        try:
            await cb.message.edit_text("⚙️ <b>Адмін Панель</b>", reply_markup=admin_panel())
        except Exception:
            pass


# NOTE: XLSX exports were removed (not informative vs main report / sheet).
