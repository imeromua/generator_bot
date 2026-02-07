import logging
import sqlite3

from database.models import get_connection


def add_driver(name):
    try:
        with get_connection() as conn:
            conn.execute("INSERT INTO drivers (name) VALUES (?)", (name,))
        return True
    except sqlite3.IntegrityError:
        logging.warning(f"Водій {name} вже існує")
        return False
    except Exception as e:
        logging.error(f"Помилка додавання водія: {e}")
        return False


def get_drivers():
    with get_connection() as conn:
        return [r[0] for r in conn.execute("SELECT name FROM drivers").fetchall()]


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
                        "INSERT OR IGNORE INTO drivers (name) VALUES (?)",
                        (name.strip(),),
                    )
    except Exception as e:
        logging.error(f"Помилка синхронізації водіїв: {e}")


def delete_driver(name):
    with get_connection() as conn:
        conn.execute("DELETE FROM drivers WHERE name = ?", (name,))
