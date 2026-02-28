"""Permission helpers for admin access checks."""

import config


def is_admin(user: dict | None) -> bool:
    """Перевіряє чи є користувач адміністратором."""
    if not user:
        return False
    try:
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        return False
    return bool(user_id and user_id in config.ADMIN_IDS)
