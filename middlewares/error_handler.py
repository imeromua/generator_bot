"""Error handling middleware and utilities.

Provides comprehensive error handling for the bot with admin notifications.
"""
import logging
import traceback
from typing import Callable, Any, Awaitable, Optional, TypeVar
from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, ErrorEvent
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNetworkError
from datetime import datetime
import config

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ErrorHandlerMiddleware(BaseMiddleware):
    """Мідлвар для перехоплення помилок на рівні update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Optional[Any]:
        """Handle errors from event processing.

        Args:
            handler: Next handler in chain
            event: Telegram event
            data: Handler data

        Returns:
            Handler result or None if error occurred
        """
        try:
            return await handler(event, data)

        except TelegramBadRequest as e:
            # Помилки типу "message not found", "chat not found" тощо
            logger.warning(f"⚠️ TelegramBadRequest: {e}")
            # Не падаємо, просто логуємо
            return None

        except TelegramNetworkError as e:
            # Мережеві помилки (timeout, connection error)
            logger.error(f"❌ TelegramNetworkError: {e}")
            # Можна спробувати повторити через час
            return None

        except Exception as e:
            # Всі інші помилки
            logger.error(f"💥 Необроблена помилка в middleware: {e}", exc_info=True)

            # Відправка повідомлення адміну про помилку
            try:
                await self._notify_admin(event, e, data)
            except Exception:
                pass

            return None

    async def _notify_admin(
        self,
        event: TelegramObject,
        error: Exception,
        data: dict[str, Any]
    ) -> None:
        """Відправляє повідомлення адміну про помилку.

        Args:
            event: Telegram event that caused error
            error: Exception that occurred
            data: Handler data with bot instance
        """
        try:
            bot: Optional[Bot] = data.get("bot")
            if not bot or not config.ADMIN_IDS:
                return

            # Інформація про update
            update_info = "Unknown"
            user_info = "Unknown"

            if hasattr(event, 'from_user') and event.from_user:
                user = event.from_user
                user_info = f"@{user.username or 'no_username'} (ID: {user.id})"

            if hasattr(event, 'text'):
                update_info = event.text[:100]
            elif hasattr(event, 'data'):
                update_info = f"Callback: {event.data}"

            # Трейсбек
            tb = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
            tb_short = '\n'.join(tb.split('\n')[-10:])  # Останні 10 рядків

            error_msg = (
                f"🚨 <b>ПОМИЛКА В БОТІ</b>\n\n"
                f"👤 Користувач: {user_info}\n"
                f"📝 Update: <code>{update_info}</code>\n\n"
                f"❌ Помилка: <code>{type(error).__name__}</code>\n"
                f"💬 Текст: <code>{str(error)}</code>\n\n"
                f"📍 Трейсбек:\n<code>{tb_short}</code>"
            )

            # Обмеження довжини повідомлення
            if len(error_msg) > 4000:
                error_msg = error_msg[:3900] + "\n...\n(трейсбек обрізано)"

            for admin_id in config.ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, error_msg)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Помилка при відправці повідомлення адміну: {e}")


async def global_error_handler(event: ErrorEvent, data: dict[str, Any]) -> None:
    """Глобальний обробник помилок для aiogram.

    Спрацьовує коли помилка не була оброблена middleware.

    Args:
        event: Error event with exception info
        data: Handler data
    """
    logger.error(f"💥 Глобальна помилка: {event.exception}", exc_info=event.exception)

    # Спроба відправити повідомлення користувачу
    if event.update.message:
        try:
            await event.update.message.answer(
                "⚠️ Виникла помилка при обробці запиту.\n"
                "Спробуйте ще раз або зверніться до адміністратора."
            )
        except Exception:
            pass
    elif event.update.callback_query:
        try:
            await event.update.callback_query.answer(
                "⚠️ Помилка обробки. Спробуйте ще раз.",
                show_alert=True
            )
        except Exception:
            pass


def safe_execute(default_return: Optional[T] = None) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[Optional[T]]]]:
    """Декоратор для безпечного виконання функцій.

    При помилці повертає default_return замість падіння.

    Args:
        default_return: Value to return on error

    Returns:
        Decorated function that catches exceptions
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[Optional[T]]]:
        async def wrapper(*args: Any, **kwargs: Any) -> Optional[T]:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.error(f"❌ Помилка в {func.__name__}: {e}", exc_info=True)
                return default_return
        return wrapper
    return decorator
