import csv
import logging
import os
from datetime import datetime, timedelta

from aiogram import Router, F, types

import config
import database.db_api as db
from keyboards.builders import admin_panel
from services.logs_xlsx_export import generate_logs_report_xlsx
from services.month_sheet_export import generate_month_sheet_xlsx

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


async def _handle_export_events_xlsx(cb: types.CallbackQuery, start_date: str, end_date: str):
    """Export events from sheet 'ПОДІЇ' to Excel with styles and human caption."""

    filename = None
    try:
        filename, caption = await generate_logs_report_xlsx(
            start_date=start_date,
            end_date=end_date,
            sheet_name="ПОДІЇ",
        )

        if not filename:
            await cb.answer("ℹ️ Немає подій за цей період", show_alert=True)
            try:
                await cb.message.edit_text("⚙️ <b>Адмін Панель</b>", reply_markup=admin_panel())
            except Exception:
                pass
            return

        nav_kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="⚙️ Адмін панель", callback_data="admin_home"),
                types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home"),
            ]
        ])

        await cb.message.answer_document(types.FSInputFile(filename), caption=caption, reply_markup=nav_kb)
        await cb.answer("✅ Готово", show_alert=True)

    except Exception as e:
        logger.error(f"XLSX export error: {e}", exc_info=True)
        await cb.answer("❌ Помилка експорту", show_alert=True)

    finally:
        try:
            if filename and os.path.exists(filename):
                os.remove(filename)
        except Exception:
            pass

        try:
            await cb.message.edit_text("⚙️ <b>Адмін Панель</b>", reply_markup=admin_panel())
        except Exception:
            pass


@router.callback_query(F.data == "export_month_sheet")
async def export_month_sheet(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        await cb.message.edit_text(f"⏳ Готую місячний Excel ({config.SHEET_NAME})...")
    except Exception:
        pass

    filename = None
    try:
        filename, caption = await generate_month_sheet_xlsx(sheet_name=config.SHEET_NAME)

        if not filename:
            await cb.answer(caption or "❌ Помилка експорту", show_alert=True)
            try:
                await cb.message.edit_text("⚙️ <b>Адмін Панель</b>", reply_markup=admin_panel())
            except Exception:
                pass
            return

        nav_kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="⚙️ Адмін панель", callback_data="admin_home"),
                types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home"),
            ]
        ])

        await cb.message.answer_document(types.FSInputFile(filename), caption=caption, reply_markup=nav_kb)
        await cb.answer("✅ Готово", show_alert=True)

    except Exception as e:
        logger.error(f"Month sheet export error: {e}", exc_info=True)
        await cb.answer("❌ Помилка експорту", show_alert=True)

    finally:
        try:
            if filename and os.path.exists(filename):
                os.remove(filename)
        except Exception:
            pass

        try:
            await cb.message.edit_text("⚙️ <b>Адмін Панель</b>", reply_markup=admin_panel())
        except Exception:
            pass


@router.callback_query(F.data == "export_logs_yesterday")
async def export_logs_yesterday(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    now = datetime.now(config.KYIV)
    end_d = (now - timedelta(days=1)).date()
    start_d = end_d

    start_str = start_d.strftime("%Y-%m-%d")
    end_str = end_d.strftime("%Y-%m-%d")

    try:
        await cb.message.edit_text("⏳ Готую Excel (події за вчора)...")
    except Exception:
        pass

    await _handle_export_events_xlsx(cb, start_str, end_str)


@router.callback_query(F.data == "export_logs_7d")
async def export_logs_7d(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    now = datetime.now(config.KYIV)
    end_d = (now - timedelta(days=1)).date()  # сьогодні не враховуємо
    start_d = end_d - timedelta(days=6)

    start_str = start_d.strftime("%Y-%m-%d")
    end_str = end_d.strftime("%Y-%m-%d")

    try:
        await cb.message.edit_text("⏳ Готую Excel (події за останні 7 днів, без сьогодні)...")
    except Exception:
        pass

    await _handle_export_events_xlsx(cb, start_str, end_str)
