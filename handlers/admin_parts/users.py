from aiogram import Router, F, types

import config
import database.db_api as db
from keyboards.builders import admin_panel

router = Router()


# --- ЮЗЕРИ ---
@router.callback_query(F.data == "users_list")
async def users_view(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    users = db.get_all_users()
    txt = "👥 <b>Користувачі в БД:</b>\n\n"

    if not users:
        txt += "<i>Поки немає зареєстрованих користувачів</i>"
    else:
        for uid, name in users:
            txt += f"👤 {name}\n🆔 <code>{uid}</code>\n\n"
        txt += "<i>Натисніть на ID, щоб скопіювати.</i>"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ])
    await cb.message.edit_text(txt, reply_markup=kb)
