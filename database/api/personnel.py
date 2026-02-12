import logging

from database.models import get_connection


def set_personnel_for_user(user_id: int, personnel_name: str | None):
    """Призначає ПІБ (з колонки 'ПЕРСОНАЛ') для Telegram користувача."""
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
            ORDER BY LOWER(u.full_name)
            """
        ).fetchall()
        return rows


def get_personnel_names():
    """Get all personnel names as list."""
    with get_connection() as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT name FROM personnel_names ORDER BY LOWER(name)"
            ).fetchall()
        ]


def add_personnel_name(name):
    """Add personnel name. Returns True if inserted, False if already existed."""
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


def update_personnel_name(old_name, new_name):
    """Update personnel name. Returns True if successful, False if new_name already exists."""
    if not old_name or not new_name:
        return False
    
    old_name = old_name.strip()
    new_name = new_name.strip()
    
    if old_name == new_name:
        return True
    
    try:
        with get_connection() as conn:
            # Check if new name already exists
            exists = conn.execute(
                "SELECT 1 FROM personnel_names WHERE name = ?",
                (new_name,)
            ).fetchone()
            
            if exists:
                logging.warning(f"Персонал {new_name} вже існує")
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
            
            return bool(cur.rowcount and cur.rowcount > 0)
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        logging.error(f"Помилка оновлення персоналу: {e}")
        return False


def delete_personnel_name(name):
    """Delete personnel name. Also clears user assignments. Returns True if deleted."""
    if not name:
        return False
    
    try:
        with get_connection() as conn:
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
            
            return bool(cur.rowcount and cur.rowcount > 0)
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        logging.error(f"Помилка видалення персоналу: {e}")
        return False


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
                        """
                        INSERT INTO personnel_names (name) VALUES (?)
                        ON CONFLICT(name) DO NOTHING
                        """,
                        (str(name).strip(),),
                    )
    except Exception as e:
        logging.error(f"Помилка синхронізації персоналу: {e}")
