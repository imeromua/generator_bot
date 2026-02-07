from datetime import datetime

import config
import database.db_api as db


def ensure_admin_user(user_id: int, first_name: str | None = None):
    """Гарантує, що адмін є в таблиці users, щоб не падати на user[1]."""
    user = db.get_user(user_id)
    if user:
        return user

    if user_id in config.ADMIN_IDS:
        name = f"Admin {first_name or ''}".strip()
        if not name:
            name = f"Admin {user_id}"
        try:
            db.register_user(user_id, name)
        except Exception:
            pass
        return db.get_user(user_id)

    return None


def actor_name(user_id: int, first_name: str | None = None) -> str:
    user = db.get_user(user_id)
    if user and user[1]:
        return str(user[1])
    if user_id in config.ADMIN_IDS:
        user = ensure_admin_user(user_id, first_name=first_name)
        if user and user[1]:
            return str(user[1])
    return str(user_id)


def fmt_state_ts(ts_raw: str | None) -> str:
    s = (ts_raw or "").strip()
    if not s:
        return "—"
    try:
        dt = datetime.fromtimestamp(int(float(s)), tz=config.KYIV)
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return s
