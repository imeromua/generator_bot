import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database.db_api as db
from services.parser import parse_dtek_message

logger = logging.getLogger(__name__)

router = Router()

@router.message(F.text & ~F.text.startswith("/"), StateFilter(None))
async def check_dtek_post(msg: types.Message):
    """Перевіряє кожен текст: чи це графік? (тільки для адмінів)"""
    if msg.from_user.id not in config.ADMIN_IDS:
        return

    ranges = parse_dtek_message(msg.text)

    if ranges:
        txt = "🕵️‍♂️ <b>Знайдено графік для 3.2:</b>\n"
        kb = []
        for s, e in ranges:
            txt += f"🔴 {s} - {e}\n"
            kb.append([InlineKeyboardButton(text=f"Застосувати {s}-{e}", callback_data=f"apply_{s}_{e}")])

        kb.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="home")])
        await msg.reply(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("apply_"))
async def apply_schedule_range(cb: types.CallbackQuery):
    """Записує знайдений графік у БД (тільки для адмінів)"""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        parts = cb.data.split("_")
        s_str, e_str = parts[1], parts[2]

        s_h = int(s_str.split(":")[0])
        e_h = int(e_str.split(":")[0])

        if e_h == 0:
            e_h = 24

        date_str = datetime.now(config.KYIV).strftime("%Y-%m-%d")
        db.set_schedule_range(date_str, s_h, e_h)

        await cb.message.edit_text(f"✅ <b>Графік оновлено!</b>\n🔴 {s_str} - {e_str}")
        await cb.answer()

    except Exception as e:
        logger.error(f"Parser Error: {e}", exc_info=True)
        await cb.answer("❌ Помилка обробки", show_alert=True)