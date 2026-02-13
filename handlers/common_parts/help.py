from aiogram import Router, types
from aiogram.filters import Command

import config
import database.db_api as db


router = Router()


def _nav_kb(user_id: int) -> types.InlineKeyboardMarkup:
    kb = [[types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")]]
    if user_id in config.ADMIN_IDS:
        kb.insert(0, [types.InlineKeyboardButton(text="⚙️ Адмін панель", callback_data="admin_home")])
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


async def _delete_old_ui_message(user_id: int, bot):
    """Видаляє старе UI повідомлення для збереження single-window концепції."""
    try:
        prev = db.get_ui_message(user_id)
        if prev:
            prev_chat_id, prev_msg_id = prev
            try:
                await bot.delete_message(chat_id=prev_chat_id, message_id=prev_msg_id)
            except Exception:
                pass
    except Exception:
        pass


@router.message(Command("help"))
async def cmd_help(msg: types.Message):
    """Вбудована довідка."""
    txt = (
        "ℹ️ <b>Довідка</b>\n\n"
        "Цей бот веде облік роботи генераторів: зміни, паливо, ТО, графік відключень та синхронізацію з Google Sheets.\n\n"
        "<b>🏠 Головне меню</b>\n"
        "• <b>СТАРТ</b> — відкриває доступну зміну (1 → 2 → 3; <b>Екстра</b> доступна після завершення 1–3).\n"
        "• <b>СТОП</b> — закриває активну зміну (фіксує час роботи та витрати палива).\n"
        "• <b>📥 ПРИЙОМ ПАЛИВА</b> — реєстрація заправки (водій → літри → номер чека).\n"
        "• <b>🕘 Останні події</b> — журнал старт/стоп/заправок/ТО/синхронізацій.\n"
        "• <b>📅 Графік відключень</b> — план на сьогодні.\n"
        "• <b>📨 Повідомлення</b> — історія важливих повідомлень (успіхи, помилки, попередження, алерти).\n\n"
        "<b>⛽ Паливо на головній</b>\n"
        "• <b>Залишок палива</b> — показує поточний залишок. Якщо генератор <b>працює</b>, залишок може відображатись як <b>(оцінка)</b> — розрахунок «на льоту» від часу роботи.\n"
        "• <b>Вистачить на</b> — орієнтовний час роботи, рахується від поточного/оцінкового залишку та витрати <b>FUEL_CONSUMPTION</b> (або <b>FUEL_RATE</b> для сумісності) з .env, в л/год.\n\n"
        "<b>🕒 Обмеження (робочий час)</b>\n"
        "• Поза робочим часом (<b>WORK_START_TIME–WORK_END_TIME</b>) заборонено: <b>СТАРТ</b> та <b>ПРИЙОМ ПАЛИВА</b>.\n\n"
        "<b>🔌 Два генератори</b>\n"
        "• Система підтримує <b>основний</b> та <b>аварійний</b> генератори.\n"
        "• Активний генератор показується в адмін‑панелі; всі дії (зміни, паливо, ТО) стосуються саме його.\n"
        "• Аварійний генератор <b>НЕ синхронізується</b> з Google Sheets — дані зберігаються тільки в БД.\n"
        "• Для аварійного доступний окремий Excel‑звіт та архів звітів (через меню \"Перемикання генераторів\").\n\n"
        "<b>⚙️ Адмінам</b>\n"
        "• <b>🧠 Розумна синхронізація</b> — автоматично синхронізує дані між БД та Google Sheets. "
        "Порівнює дані по датах, синхронізує тільки зміни, автоматично вирішує конфлікти, перевіряє витрати палива "
        "та оновлює довідники (водії/персонал). <b>Можлива тільки коли генератор вимкнено (OFF)</b>.\n"
        "• <b>🔄 Перемикання генераторів</b> — вибір активного генератора (основний/аварійний), перегляд статистики, "
        "експорт Excel‑звіту по аварійному генератору та доступ до архіву звітів.\n"
        "• <b>🛠 Меню ТО</b> — заміна мастила та свічок, історія ТО, корекція мотогодин для обох генераторів.\n"
        "• <b>👥 Персонал</b> — прив'язка користувачів до ПІБ персоналу.\n"
        "• <b>🚛 Водії</b> — додавання нових водіїв для вибору при прийомі палива.\n"
        "• <b>📅 Графік відключень</b> — редагування графіку на сьогодні/завтра, сповіщення про зміни.\n"
        "• Інші пункти меню адмін‑панелі — сервісні інструменти для адміністрування (ID користувачів, очистка БД тощо).\n\n"
        "<b>ℹ️ Якщо бачите</b> «Нема прив'язки до персоналу» — попросіть адміна призначити вам ПІБ.\n\n"
        "📖 Політика приватності: /privacy"
    )

    # FIX: Видаляємо старе UI повідомлення для збереження single-window
    await _delete_old_ui_message(msg.from_user.id, msg.bot)

    sent = await msg.answer(txt, reply_markup=_nav_kb(msg.from_user.id))
    
    # FIX: Зберігаємо нове UI message ID
    try:
        db.set_ui_message(msg.from_user.id, sent.chat.id, sent.message_id)
    except Exception:
        pass


@router.message(Command("privacy"))
async def cmd_privacy(msg: types.Message):
    """Коротка політика приватності."""
    txt = (
        "🔒 <b>Політика приватності</b>\n\n"
        "<b>Які дані зберігаються:</b>\n"
        "• Ваш Telegram ID та ім'я\n"
        "• ПІБ (якщо адмін призначив прив'язку до персоналу)\n"
        "• Журнал подій:\n"
        "  - старт/стоп змін з часом\n"
        "  - прийом палива (літри, чек, водій)\n"
        "  - технічне обслуговування\n"
        "  - корекції (тільки для адмінів)\n\n"
        "<b>Як використовуються дані:</b>\n"
        "• Облік роботи генератора\n"
        "• Розумна синхронізація з Google Sheets вашої організації\n"
        "• Формування звітів та статистики\n"
        "• Нагадування про ТО та заправки\n\n"
        "<b>Безпека:</b>\n"
        "• Дані зберігаються локально в БД\n"
        "• Доступ до Google Sheets обмежений service account\n"
        "• Тільки адміни мають доступ до корекцій та синхронізації\n"
        "• Синхронізація можлива тільки коли генератор вимкнено\n"
        "• Блокування одночасних синхронізацій (lock mechanism)\n\n"
        "<b>Ваші права:</b>\n"
        "Щоб видалити ваш запис або виправити дані — зверніться до адміністраторів. Вони можуть:\n"
        "• Відредагувати ваше ПІБ\n"
        "• Видалити прив'язку до персоналу\n"
        "• Очистити журнал подій (якщо потрібно)\n\n"
        "📧 Питання? Напишіть адміну вашої організації."
    )

    # FIX: Видаляємо старе UI повідомлення для збереження single-window
    await _delete_old_ui_message(msg.from_user.id, msg.bot)

    sent = await msg.answer(txt, reply_markup=_nav_kb(msg.from_user.id))
    
    # FIX: Зберігаємо нове UI message ID
    try:
        db.set_ui_message(msg.from_user.id, sent.chat.id, sent.message_id)
    except Exception:
        pass


# FIX: Add callback handler for "home" button to return to dashboard
@router.callback_query(lambda cb: cb.data == "home")
async def cb_home(cb: types.CallbackQuery):
    """Повернення на головну сторінку (дашборд)."""
    from handlers.common_parts.dash import show_dash
    
    user_id = cb.from_user.id
    user_info = db.get_user(user_id)
    user_name = user_info[1] if user_info else cb.from_user.full_name
    
    await show_dash(cb.message, user_id, user_name)
    await cb.answer()
