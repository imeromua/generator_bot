"""FIX #25: Messaging utility for automatic message history.

Цей модуль надає зручні функції для автоматичного збереження
важливих повідомлень в історію користувача.
"""

import logging
from typing import Optional

import database.db_api as db

logger = logging.getLogger(__name__)


def notify_success(user_id: int, message: str, save_to_history: bool = True) -> None:
    """Повідомлення про успішну операцію.

    Args:
        user_id: Telegram user ID
        message: Текст повідомлення
        save_to_history: Зберегти в історію (за замовчуванням True)
    """
    if save_to_history:
        try:
            db.add_message(user_id, message, "success")
            logger.info(f"✅ Success message saved for user {user_id}: {message}")
        except Exception as e:
            logger.error(f"Failed to save success message: {e}", exc_info=True)


def notify_error(user_id: int, message: str, save_to_history: bool = True) -> None:
    """Повідомлення про помилку.

    Args:
        user_id: Telegram user ID
        message: Текст повідомлення
        save_to_history: Зберегти в історію (за замовчуванням True)
    """
    if save_to_history:
        try:
            db.add_message(user_id, message, "error")
            logger.error(f"❌ Error message saved for user {user_id}: {message}")
        except Exception as e:
            logger.error(f"Failed to save error message: {e}", exc_info=True)


def notify_warning(user_id: int, message: str, save_to_history: bool = True) -> None:
    """Повідомлення-попередження.

    Args:
        user_id: Telegram user ID
        message: Текст повідомлення
        save_to_history: Зберегти в історію (за замовчуванням True)
    """
    if save_to_history:
        try:
            db.add_message(user_id, message, "warning")
            logger.warning(f"⚠️ Warning message saved for user {user_id}: {message}")
        except Exception as e:
            logger.error(f"Failed to save warning message: {e}", exc_info=True)


def notify_alert(user_id: int, message: str, save_to_history: bool = True) -> None:
    """Важливий алерт.

    Args:
        user_id: Telegram user ID
        message: Текст повідомлення
        save_to_history: Зберегти в історію (за замовчуванням True)
    """
    if save_to_history:
        try:
            db.add_message(user_id, message, "alert")
            logger.info(f"🔔 Alert message saved for user {user_id}: {message}")
        except Exception as e:
            logger.error(f"Failed to save alert message: {e}", exc_info=True)


def notify_info(user_id: int, message: str, save_to_history: bool = True) -> None:
    """Інформаційне повідомлення.

    Args:
        user_id: Telegram user ID
        message: Текст повідомлення
        save_to_history: Зберегти в історію (за замовчуванням True)
    """
    if save_to_history:
        try:
            db.add_message(user_id, message, "info")
            logger.info(f"ℹ️ Info message saved for user {user_id}: {message}")
        except Exception as e:
            logger.error(f"Failed to save info message: {e}", exc_info=True)


def notify_all_users(message: str, message_type: str = "info", admin_only: bool = False) -> int:
    """Відправляє повідомлення всім користувачам.

    Args:
        message: Текст повідомлення
        message_type: Тип (info, success, warning, error, alert)
        admin_only: Тільки адмінам (за замовчуванням False)

    Returns:
        Кількість користувачів, яким відправлено повідомлення
    """
    import config

    count = 0
    try:
        users = db.get_all_users()

        for user_id, _ in users:
            if admin_only and user_id not in config.ADMIN_IDS:
                continue

            try:
                db.add_message(user_id, message, message_type)
                count += 1
            except Exception as e:
                logger.error(f"Failed to send message to user {user_id}: {e}")

        logger.info(f"📢 Broadcast message sent to {count} users: {message}")
    except Exception as e:
        logger.error(f"Failed to broadcast message: {e}", exc_info=True)

    return count
