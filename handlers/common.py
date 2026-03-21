"""Common handlers - minimal bot with only /start command."""

import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.markdown import hbold

import config
import database.db_api as db

logger = logging.getLogger(__name__)

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message):
    """
    Обробник команди /start.
    Відображає привітання та кнопку для відкриття Mini App.
    """
    user_id = message.from_user.id
    username = message.from_user.username or None
    full_name = message.from_user.full_name or "User"

    # Реєстрація користувача в базі (якщо новий)
    try:
        db.create_user(
            user_id=user_id,
            username=username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            role="user",
        )
    except Exception as e:
        logger.error(f"Failed to register user {user_id}: {e}")

    # Перевірка прав доступу
    is_admin = user_id in config.ADMIN_IDS

    try:
        has_personnel = bool(db.get_personnel_for_user(user_id))
    except Exception:
        has_personnel = False

    # Формування привітального повідомлення
    greeting = f"👋 Вітаю, {hbold(full_name)}!\n\n"

    if is_admin:
        greeting += f"🔑 {hbold('Адміністратор')}\n\n"
    elif not has_personnel:
        # Тільки для звичайних користувачів без персоналу
        greeting += "⚠️ Ви не прив'язані до персоналу.\nЗверніться до адміністратора для доступу.\n\n"

    greeting += (
        f"🚀 Натисніть кнопку нижче, щоб відкрити {hbold('Mini App')}:\n\n"
        "📱 У Mini App ви можете:\n"
        "  • Переглядати стан генератора\n"
        "  • Керувати змінами\n"
        "  • Приймати паливо\n"
        "  • Переглядати графіки та аналітику\n"
    )

    if is_admin:
        greeting += "  • Адмін-панель з повним функціоналом\n"

    # Кнопка відкриття WebApp
    if config.WEBAPP_URL:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📱 Відкрити Mini App", web_app=WebAppInfo(url=config.WEBAPP_URL))]
            ]
        )
        await message.answer(greeting, reply_markup=keyboard)
    else:
        await message.answer(greeting + f"\n\n❌ {hbold('Mini App недоступний')} (WEBAPP_URL не налаштовано)")


@router.message(F.text)
async def handle_any_text(message: Message):
    """
    Fallback handler для будь-яких текстових повідомлень.
    Нагадує користувачу використовувати Mini App.
    """
    await message.answer(
        f"ℹ️ Цей бот працює через {hbold('Mini App')}.\n\n"
        "Будь ласка, використовуйте команду /start та відкрийте Mini App."
    )
