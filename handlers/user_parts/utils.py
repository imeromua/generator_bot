"""User utilities.

Helper functions for user handlers.
"""

from typing import Optional

import config
import database.db_api as db


def ensure_user(user_id: int, first_name: Optional[str] = None) -> Optional[tuple]:
    """Повертає (user_id, full_name) з БД. Якщо адмін без запису — авто-реєструє.

    Args:
        user_id: Telegram user ID
        first_name: User's first name (optional)

    Returns:
        Tuple of (user_id, full_name) or None if user not registered
    """
    user = db.get_user(user_id)
    if user:
        return user

    if user_id in config.ADMIN_IDS:
        name = f"Admin {first_name or ''}".strip()
        if not name:
            name = f"Admin {user_id}"
        db.register_user(user_id, name)
        return db.get_user(user_id)

    return None


def get_operator_personnel_name(user_id: int) -> Optional[str]:
    """Повертає ПІБ з 'ПЕРСОНАЛ' для запису у таблицю. Якщо не призначено — None.

    Args:
        user_id: Telegram user ID

    Returns:
        Personnel name or None if not assigned
    """
    try:
        return db.get_personnel_for_user(user_id)
    except Exception:
        return None
