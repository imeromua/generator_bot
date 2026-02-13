"""User management API.

Provides functions for user registration and retrieval.
"""
from typing import Optional

from database.models import get_connection


def register_user(user_id: int, name: str) -> None:
    """Register or update a user.

    Args:
        user_id: Telegram user ID
        name: User's full name
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, full_name) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name
            """,
            (user_id, name),
        )


def get_user(user_id: int) -> Optional[tuple[int, str]]:
    """Get user by ID.

    Args:
        user_id: Telegram user ID

    Returns:
        Tuple of (user_id, full_name) or None if not found
    """
    with get_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def get_all_users() -> list[tuple[int, str]]:
    """Get all registered users.

    Returns:
        List of tuples (user_id, full_name)
    """
    with get_connection() as conn:
        return conn.execute("SELECT user_id, full_name FROM users").fetchall()
