import logging

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
from database.models import get_connection

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "db_cleanup_confirm")
async def db_cleanup_confirm(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    txt = (
        "⚠️ <b>Очистка бази даних</b>\n\n"
        "Ця операція видалить ВСІ дані з БД:\n"
        "• Журнал подій (logs)\n"
        "• Графік відключень (schedule)\n"
        "• Водії (drivers)\n"
        "• Персонал (personnel_names, user_personnel)\n"
        "• Користувачі (users)\n"
        "• ТО (maintenance)\n\n"
        "🔴 <b>generator_state</b> буде скинуто до дефолтних значень (0.0 паливо/мотогодини/ТО).\n\n"
        "💾 Рекомендується спочатку зробити експорт в Sheets як резервну копію!\n\n"
        "❌ <b>Цю операцію НЕМОЖЛИВО ВІДМІНИТИ!</b>"
    )

    kb = [
        [InlineKeyboardButton(text="✅ Підтверджую очистку", callback_data="db_cleanup_execute")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="admin_home")],
    ]
    await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


@router.callback_query(F.data == "db_cleanup_execute")
async def db_cleanup_execute(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.answer("⏳ Очистка БД...", show_alert=False)
    await cb.message.edit_text("⏳ <b>Очистка бази даних...</b>\n\nЗачекайте...")

    try:
        with get_connection() as conn:
            # Видаляємо всі дані (схема залишається)
            conn.execute("DELETE FROM logs")
            conn.execute("DELETE FROM schedule")
            conn.execute("DELETE FROM drivers")
            conn.execute("DELETE FROM personnel_names")
            conn.execute("DELETE FROM user_personnel")
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM maintenance")
            conn.execute("DELETE FROM user_ui")
            conn.execute("DELETE FROM user_messages")

            # Скидаємо generator_state до дефолтів
            conn.execute("UPDATE generator_state SET value = '0.0' WHERE key = 'total_hours'")
            conn.execute("UPDATE generator_state SET value = '0.0' WHERE key = 'last_oil_change'")
            conn.execute("UPDATE generator_state SET value = '0.0' WHERE key = 'last_spark_change'")
            conn.execute("UPDATE generator_state SET value = 'OFF' WHERE key = 'status'")
            conn.execute("UPDATE generator_state SET value = 'none' WHERE key = 'active_shift'")
            conn.execute("UPDATE generator_state SET value = '' WHERE key = 'last_start_time'")
            conn.execute("UPDATE generator_state SET value = '' WHERE key = 'last_start_date'")
            conn.execute("UPDATE generator_state SET value = '0.0' WHERE key = 'current_fuel'")
            conn.execute("UPDATE generator_state SET value = '' WHERE key = 'fuel_ordered_date'")
            conn.execute("UPDATE generator_state SET value = '' WHERE key = 'stop_reminder_sent_date'")
            # Скидаємо стан аварійного генератора
            conn.execute("UPDATE generator_state SET value = 'main' WHERE key = 'active_generator'")
            conn.execute("UPDATE generator_state SET value = '0.0' WHERE key = 'emergency_total_hours'")
            conn.execute("UPDATE generator_state SET value = '0.0' WHERE key = 'emergency_last_oil_change'")
            conn.execute("UPDATE generator_state SET value = '0.0' WHERE key = 'emergency_last_spark_change'")

        logger.info(f"✅ БД очищено адміном {cb.from_user.id}")

        txt = (
            "✅ <b>База даних очищена!</b>\n\n"
            "• Всі події видалені\n"
            "• Графік очищено\n"
            "• Водії/персонал видалені\n"
            "• Стан генератора скинуто до нуля\n\n"
            "📌 Тепер можете зробити імпорт з Sheets, щоб завантажити дані."
        )

        kb = [[InlineKeyboardButton(text="🔙 В адмінку", callback_data="admin_home")]]
        await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    except Exception as e:
        logger.error(f"❌ Помилка очистки БД: {e}", exc_info=True)
        kb = [[InlineKeyboardButton(text="🔙 В адмінку", callback_data="admin_home")]]
        await cb.message.edit_text(
            f"❌ <b>Помилка очистки</b>\n\n{e}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
