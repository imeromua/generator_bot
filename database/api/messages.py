"""FIX #25: User message history API with automatic rotation (max 5 per user).

Цей модуль надає функціонал для:
- Збереження повідомлень (алерти, підтвердження, помилки)
- Автоматичної ротації (максимум 5 повідомлень на користувача)
- Отримання історії повідомлень
"""

import logging
from datetime import datetime

import config
from database.models import get_connection

logger = logging.getLogger(__name__)

# Максимальна кількість повідомлень на користувача
MAX_MESSAGES_PER_USER = 5


def add_message(user_id: int, message_text: str, message_type: str = "info") -> None:
    """Зберігає повідомлення для користувача з автоматичною ротацією.

    Args:
        user_id: Telegram user ID
        message_text: Текст повідомлення
        message_type: Тип повідомлення (info, success, warning, error, alert)

    Якщо у користувача вже є MAX_MESSAGES_PER_USER повідомлень,
    видаляється найстаріше перед додаванням нового.
    """
    timestamp = datetime.now(config.KYIV).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        try:
            # Перевіряємо кількість повідомлень
            count_query = "SELECT COUNT(*) FROM user_messages WHERE user_id = ?"
            count = conn.execute(count_query, (user_id,)).fetchone()[0]

            # Якщо досягнуто ліміт - видаляємо найстаріше
            if count >= MAX_MESSAGES_PER_USER:
                delete_query = """
                    DELETE FROM user_messages
                    WHERE id = (
                        SELECT id FROM user_messages
                        WHERE user_id = ?
                        ORDER BY timestamp ASC
                        LIMIT 1
                    )
                """
                conn.execute(delete_query, (user_id,))
                logger.debug(f"🗑️ Видалено найстаріше повідомлення для user_id={user_id}")

            # Додаємо нове повідомлення
            insert_query = """
                INSERT INTO user_messages (user_id, message_text, message_type, timestamp)
                VALUES (?, ?, ?, ?)
            """
            conn.execute(insert_query, (user_id, message_text, message_type, timestamp))
            logger.info(f"📨 Збережено повідомлення [{message_type}] для user_id={user_id}")

        except Exception as e:
            logger.error(f"⚠️ Помилка збереження повідомлення: {e}", exc_info=True)


def get_user_messages(user_id: int, limit: int = 5) -> list[tuple[str, str, str]]:
    """Отримує останні повідомлення користувача.

    Args:
        user_id: Telegram user ID
        limit: Максимальна кількість повідомлень

    Returns:
        List of tuples: (message_text, message_type, timestamp)
    """
    with get_connection() as conn:
        try:
            query = """
                SELECT message_text, message_type, timestamp
                FROM user_messages
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            rows = conn.execute(query, (user_id, limit)).fetchall()
            return rows
        except Exception as e:
            logger.error(f"⚠️ Помилка отримання повідомлень: {e}", exc_info=True)
            return []


def clear_user_messages(user_id: int) -> None:
    """Очищає всі повідомлення користувача.

    Args:
        user_id: Telegram user ID
    """
    with get_connection() as conn:
        try:
            query = "DELETE FROM user_messages WHERE user_id = ?"
            conn.execute(query, (user_id,))
            logger.info(f"🗑️ Очищено повідомлення для user_id={user_id}")
        except Exception as e:
            logger.error(f"⚠️ Помилка очищення повідомлень: {e}", exc_info=True)


def get_message_count(user_id: int) -> int:
    """Повертає кількість повідомлень користувача.

    Args:
        user_id: Telegram user ID

    Returns:
        Кількість повідомлень
    """
    with get_connection() as conn:
        try:
            query = "SELECT COUNT(*) FROM user_messages WHERE user_id = ?"
            count = conn.execute(query, (user_id,)).fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"⚠️ Помилка підрахунку повідомлень: {e}", exc_info=True)
            return 0
