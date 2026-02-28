"""Database helper utilities for webapp endpoints."""

from contextlib import contextmanager

import database.models as db_models
import database.db_api as db


@contextmanager
def atomic_transaction():
    """Context manager для безпечної роботи з транзакцією БД.

    Відкриває з'єднання, починає транзакцію, при успіху виконує commit,
    при помилці — rollback. З'єднання закривається у будь-якому випадку.
    """
    conn = db_models.get_connection()
    try:
        db_models.begin_transaction(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_admin_info(user: dict) -> tuple[int, str]:
    """Extract (user_id, admin_name) from validated user dict."""
    try:
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        user_id = 0
    user_info = db.get_user(user_id) if user_id else None
    admin_name = user_info[1] if user_info else user.get("first_name", "Адмін")
    return user_id, admin_name
