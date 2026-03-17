"""Permission helpers for admin access checks."""

import logging

import config

logger = logging.getLogger(__name__)

try:
    import database.db_api as _db
except Exception:  # pragma: no cover
    _db = None


def is_admin(user: dict | None) -> bool:
    """Перевіряє чи є користувач адміністратором (за ADMIN_IDS або роллю в БД)."""
    if not user:
        return False
    # Fast path: role already present in dict (e.g. SD JWT auth)
    direct_role = user.get("role")
    if direct_role in ("admin", "superadmin"):
        return True
    try:
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        return False
    if not user_id:
        return False
    # Check ADMIN_IDS from config
    if user_id in config.ADMIN_IDS:
        return True
    # Check role from DB
    if _db is not None:
        try:
            db_user = _db.get_user(user_id)
            if db_user:
                role = _get_role(db_user)
                return role in ("admin", "superadmin")
        except Exception:
            logger.debug("is_admin DB lookup failed for user %s", user_id, exc_info=True)
    return False


def get_user_role(user: dict | None) -> str:
    """Return the role of the user from DB, or 'user' as default."""
    if not user:
        return "user"
    try:
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        return "user"
    if not user_id:
        return "user"
    if _db is not None:
        try:
            db_user = _db.get_user(user_id)
            if db_user:
                role = _get_role(db_user)
                return role if role else ("admin" if user_id in config.ADMIN_IDS else "user")
        except Exception:
            logger.debug("get_user_role DB lookup failed for user %s", user_id, exc_info=True)
    return "admin" if user_id in config.ADMIN_IDS else "user"


def _get_role(db_user) -> str:
    """Extract role from a DB user row (tuple or dict)."""
    if db_user is None:
        return "user"
    if isinstance(db_user, dict):
        return db_user.get("role", "user") or "user"
    # It's a tuple; role is at index 5 in the new schema
    if len(db_user) > 5:
        return db_user[5] or "user"
    return "user"
