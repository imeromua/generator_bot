import logging

from database.models import get_connection


def add_driver(name):
    """Adds driver; returns True if inserted, False if already existed or error."""
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO drivers (name) VALUES (?)
                ON CONFLICT(name) DO NOTHING
                """,
                (name,),
            )
            try:
                return bool(cur.rowcount and cur.rowcount > 0)
            except Exception:
                # sqlite can be inconsistent; treat success if no exception
                return True
    except Exception as e:
        msg = str(e).lower()
        if "unique" in msg or "duplicate" in msg:
            logging.warning(f"Водій {name} вже існує")
            return False
        logging.error(f"Помилка додавання водія: {e}")
        return False


def get_drivers():
    """Get all drivers as list of names."""
    with get_connection() as conn:
        return [r[0] for r in conn.execute("SELECT name FROM drivers ORDER BY LOWER(name)").fetchall()]


def update_driver(old_name, new_name):
    """Update driver name. Returns True if successful, False if new_name already exists."""
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
                "SELECT 1 FROM drivers WHERE name = ?",
                (new_name,)
            ).fetchone()
            
            if exists:
                logging.warning(f"Водій {new_name} вже існує")
                return False
            
            # Update driver name
            cur = conn.execute(
                "UPDATE drivers SET name = ? WHERE name = ?",
                (new_name, old_name)
            )
            
            return bool(cur.rowcount and cur.rowcount > 0)
    except Exception as e:
        logging.error(f"Помилка оновлення водія: {e}")
        return False


def delete_driver(name):
    """Delete driver by name. Returns True if deleted, False if not found."""
    try:
        with get_connection() as conn:
            cur = conn.execute("DELETE FROM drivers WHERE name = ?", (name,))
            return bool(cur.rowcount and cur.rowcount > 0)
    except Exception as e:
        logging.error(f"Помилка видалення водія: {e}")
        return False


def sync_drivers_from_sheet(driver_list):
    """Повністю оновлює список водіїв у базі на основі списку з Таблиці."""
    if not driver_list:
        return

    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM drivers")
            for name in driver_list:
                if name and name.strip():
                    conn.execute(
                        """
                        INSERT INTO drivers (name) VALUES (?)
                        ON CONFLICT(name) DO NOTHING
                        """,
                        (name.strip(),),
                    )
    except Exception as e:
        logging.error(f"Помилка синхронізації водіїв: {e}")
