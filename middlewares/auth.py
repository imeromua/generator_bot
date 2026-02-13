"""Authorization middleware.

Whitelist-based access control for bot users.
"""
from typing import Any, Callable, Awaitable, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
import logging
import config

logger = logging.getLogger(__name__)


class WhitelistMiddleware(BaseMiddleware):
    """Middleware for whitelist-based authorization.

    Access rules:
    1. Admins always have access
    2. /start command with REGISTRATION_OPEN
    3. Users in WHITELIST
    4. Others are blocked
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Optional[Any]:
        """Process authorization.

        Args:
            handler: Next handler in chain
            event: Telegram event (Message or CallbackQuery)
            data: Handler data

        Returns:
            Handler result or None if blocked
        """
        # Отримуємо ID користувача (з повідомлення або кліку)
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            return await handler(event, data)

        # 1. Адміни проходять завжди
        if user_id in config.ADMIN_IDS:
            return await handler(event, data)

        # 2. Якщо це команда /start і відкрита реєстрація - пускаємо
        if isinstance(event, Message) and event.text == "/start" and config.REGISTRATION_OPEN:
            return await handler(event, data)

        # 3. Білий список (USERS) — у config це WHITELIST
        whitelist_ids = getattr(config, "WHITELIST", [])
        if user_id in whitelist_ids:
            return await handler(event, data)

        # 4. Якщо нічого не підійшло - блокуємо
        logger.info(f"⛔ Blocked by whitelist: user_id={user_id}, event={type(event).__name__}")

        if isinstance(event, Message):
            await event.answer(
                f"⛔ <b>Доступ заборонено.</b>\nВаш ID: <code>{user_id}</code>\nЗверніться до адміністратора."
            )
        elif isinstance(event, CallbackQuery):
            await event.answer("⛔ У вас немає прав доступу.", show_alert=True)

        # Перериваємо обробку (handler не викликається)
        return None
