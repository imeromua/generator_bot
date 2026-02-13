"""Personnel management API.

Manages personnel names and user-to-personnel assignments.
"""
import logging
from typing import Optional

from database.models import get_connection


def set_personnel_for_user(user_id: int, personnel_name: str | None) -> None:
    """Призначає ПІБ (з колонки 'ПЕРСОНАЛ') для Telegram користувача.

    Args:
        user_id: Telegram user ID
        personnel_name: ПІБ персоналу або None для видалення
    """
    with get_connection() as conn:
        if personnel_name is None or not str(personnel_name).strip():
            conn.execute("DELETE FROM user_personnel WHERE user_id = ?", (user_id,))
            return
        conn.execute(
            """
            INSERT INTO user_personnel (user_id, personnel_name) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET personnel_name = excluded.personnel_name
            """,
            (int(user_id), str(personnel_name).strip()),
        )


def get_personnel_for_user(user_id: int) -> str | None:
    """Отримує призначений персонал для користувача.

    Args:
        user_id: Telegram user ID

    Returns:
        ПІБ персоналу або None
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT personnel_name FROM user_personnel WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        return row[0] if row else None


def get_all_users_with_personnel() -> list[tuple[int, str, str | None]]:
    """Повертає список користувачів з прив'язкою, якщо є.

    Returns:
        List of tuples: (user_id, full_name, personnel_name)
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT u.user_id, u.full_name, up.personnel_name
            FROM users u
            LEFT JOIN user_personnel up ON up.user_id = u.user_id
            ORDER BY LOWER(u.full_name)
            """
        ).fetchall()
        return rows


def get_personnel_names() -> list[str]:
    """Get all personnel names.

    Returns:
        List of personnel names sorted alphabetically (case-insensitive)
    """
    with get_connection() as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT name FROM personnel_names ORDER BY LOWER(name)"
            ).fetchall()
        ]


def add_personnel_name(name: str) -> bool:
    """Add personnel name.

    Args:
        name: Personnel name to add

    Returns:
        True if inserted, False if already existed or error
    """
    if not name or not name.strip():
        return False

    name = name.strip()

    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO personnel_names (name) VALUES (?)
                ON CONFLICT(name) DO NOTHING
                """,
                (name,),
            )
            return bool(cur.rowcount and cur.rowcount > 0)
    except Exception as e:
        msg = str(e).lower()
        if "unique" in msg or "duplicate" in msg:
            logging.warning(f"Персонал {name} вже існує")
            return False
        logging.error(f"Помилка додавання персоналу: {e}")
        return False


def update_personnel_name(old_name: str, new_name: str) -> bool:
    """Update personnel name.

    Args:
        old_name: Current personnel name
        new_name: New personnel name

    Returns:
        True if successful, False if new_name already exists or error
    """
    if not old_name or not new_name:
        return False

    old_name = old_name.strip()
    new_name = new_name.strip()

    if old_name == new_name:
        return True

    conn = None
    try:
        conn = get_connection()

        # Check if new name already exists
        exists = conn.execute(
            "SELECT 1 FROM personnel_names WHERE name = ?",
            (new_name,)
        ).fetchone()

        if exists:
            logging.warning(f"Персонал {new_name} вже існує")
            conn.close()
            return False

        # Begin transaction to update both tables
        conn.execute("BEGIN")

        # Update in personnel_names
        cur = conn.execute(
            "UPDATE personnel_names SET name = ? WHERE name = ?",
            (new_name, old_name)
        )

        # Update in user_personnel (where users are assigned to this personnel)
        conn.execute(
            "UPDATE user_personnel SET personnel_name = ? WHERE personnel_name = ?",
            (new_name, old_name)
        )

        conn.commit()
        success = bool(cur.rowcount and cur.rowcount > 0)
        conn.close()
        return success

    except Exception as e:
        if conn:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        logging.error(f"Помилка оновлення персоналу: {e}")
        return False


def delete_personnel_name(name: str) -> bool:
    """Delete personnel name. Also clears user assignments.

    Args:
        name: Personnel name to delete

    Returns:
        True if deleted, False if not found or error
    """
    if not name:
        return False

    conn = None
    try:
        conn = get_connection()

        # Begin transaction
        conn.execute("BEGIN")

        # Delete user assignments first
        conn.execute(
            "DELETE FROM user_personnel WHERE personnel_name = ?",
            (name,)
        )

        # Delete from personnel_names
        cur = conn.execute(
            "DELETE FROM personnel_names WHERE name = ?",
            (name,)
        )

        conn.commit()
        success = bool(cur.rowcount and cur.rowcount > 0)
        conn.close()
        return success

    except Exception as e:
        if conn:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        logging.error(f"Помилка видалення персоналу: {e}")
        return False


def sync_personnel_from_sheet(personnel_list: list[str] | None) -> None:
    """Повністю оновлює список персоналу у базі на основі колонки AC з Таблиці.

    Args:
        personnel_list: List of personnel names from Google Sheets
    """
    if personnel_list is None:
        return

    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM personnel_names")
            for name in personnel_list:
                if name and str(name).strip():
                    conn.execute(
                        """
                        INSERT INTO personnel_names (name) VALUES (?)
                        ON CONFLICT(name) DO NOTHING
                        """,
                        (str(name).strip(),),
                    )
    except Exception as e:
        logging.error(f"Помилка синхронізації персоналу: {e}")
