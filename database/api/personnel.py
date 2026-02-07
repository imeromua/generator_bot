import logging

from database.models import get_connection


def set_personnel_for_user(user_id: int, personnel_name: str | None):
    """Призначає ПІБ (з колонки 'ПЕРСОНАЛ') для Telegram користувача."""
    with get_connection() as conn:
        if personnel_name is None or not str(personnel_name).strip():
            conn.execute("DELETE FROM user_personnel WHERE user_id = ?", (user_id,))
            return
        conn.execute(
            "INSERT OR REPLACE INTO user_personnel (user_id, personnel_name) VALUES (?, ?)",
            (int(user_id), str(personnel_name).strip()),
        )


def get_personnel_for_user(user_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT personnel_name FROM user_personnel WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        return row[0] if row else None


def get_all_users_with_personnel():
    """Повертає список користувачів з прив'язкою, якщо є."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT u.user_id, u.full_name, up.personnel_name
            FROM users u
            LEFT JOIN user_personnel up ON up.user_id = u.user_id
            ORDER BY u.full_name COLLATE NOCASE
            """
        ).fetchall()
        return rows


def sync_personnel_from_sheet(personnel_list):
    """Повністю оновлює список персоналу в базі на основі колонки AC з Таблиці."""
    if personnel_list is None:
        return

    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM personnel_names")
            for name in personnel_list:
                if name and str(name).strip():
                    conn.execute(
                        "INSERT OR IGNORE INTO personnel_names (name) VALUES (?)",
                        (str(name).strip(),),
                    )
    except Exception as e:
        logging.error(f"Помилка синхронізації персоналу: {e}")


def get_personnel_names():
    with get_connection() as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT name FROM personnel_names ORDER BY name COLLATE NOCASE"
            ).fetchall()
        ]
