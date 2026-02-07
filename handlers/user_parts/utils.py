import config
import database.db_api as db


def ensure_user(user_id: int, first_name: str | None = None):
    """Повертає (user_id, full_name) з БД. Якщо адмін без запису — авто-реєструє."""
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


def get_operator_personnel_name(user_id: int) -> str | None:
    """Повертає ПІБ з 'ПЕРСОНАЛ' для запису у таблицю. Якщо не призначено — None."""
    try:
        return db.get_personnel_for_user(user_id)
    except Exception:
        return None
