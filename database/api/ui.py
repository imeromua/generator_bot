"""UI state management API.

Tracks user interface message IDs for updating inline keyboards.
"""
from typing import Optional

from database.models import get_connection


def set_ui_message(user_id: int, chat_id: int, message_id: int) -> None:
    """Store UI message location for a user.

    Args:
        user_id: Telegram user ID
        chat_id: Telegram chat ID
        message_id: Telegram message ID
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_ui (user_id, chat_id, message_id) VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE
              SET chat_id = excluded.chat_id,
                  message_id = excluded.message_id
            """,
            (int(user_id), int(chat_id), int(message_id)),
        )


def get_ui_message(user_id: int) -> Optional[tuple[int, int]]:
    """Get stored UI message location for a user.

    Args:
        user_id: Telegram user ID

    Returns:
        Tuple of (chat_id, message_id) or None if not found
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT chat_id, message_id FROM user_ui WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        return (row[0], row[1]) if row else None


def clear_ui_message(user_id: int) -> None:
    """Remove stored UI message location for a user.

    Args:
        user_id: Telegram user ID
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM user_ui WHERE user_id = ?", (int(user_id),))
