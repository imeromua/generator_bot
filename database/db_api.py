import sqlite3
import logging
from datetime import datetime
from database.models import DB_NAME, get_connection

# --- USER ---
def register_user(user_id, name):
    with get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO users (user_id, full_name) VALUES (?, ?)", (user_id, name))

def get_user(user_id):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

def get_all_users():
    with get_connection() as conn:
        return conn.execute("SELECT user_id, full_name FROM users").fetchall()

# --- DRIVERS ---
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
    """
    Повністю оновлює список водіїв у базі на основі списку з Таблиці.
    """
    if not driver_list:
        return
    
    try:
        with get_connection() as conn:
            # 1. Очищаємо стару таблицю
            conn.execute("DELETE FROM drivers")
            
            # 2. Записуємо нових (INSERT OR IGNORE ігнорує дублікати)
            for name in driver_list:
                if name and name.strip():
                    conn.execute("INSERT OR IGNORE INTO drivers (name) VALUES (?)", (name.strip(),))
    except Exception as e:
        logging.error(f"Помилка синхронізації водіїв: {e}")

def delete_driver(name):
    with get_connection() as conn:
        conn.execute("DELETE FROM drivers WHERE name = ?", (name,))

# --- STATE & LOGS ---
def set_state(key, value):
    with get_connection() as conn:
        conn.execute("UPDATE generator_state SET value = ? WHERE key = ?", (str(value), key))

def get_state():
    with get_connection() as conn:
        c = conn.cursor()
        status = c.execute("SELECT value FROM generator_state WHERE key='status'").fetchone()[0]
        start_time = c.execute("SELECT value FROM generator_state WHERE key='last_start_time'").fetchone()[0]
        
        try:
            start_date = c.execute("SELECT value FROM generator_state WHERE key='last_start_date'").fetchone()[0]
        except (TypeError, IndexError):
            start_date = ''
        
        total = float(c.execute("SELECT value FROM generator_state WHERE key='total_hours'").fetchone()[0])
        last_oil = float(c.execute("SELECT value FROM generator_state WHERE key='last_oil_change'").fetchone()[0])
        
        try:
            last_spark = float(c.execute("SELECT value FROM generator_state WHERE key='last_spark_change'").fetchone()[0])
        except (TypeError, ValueError):
            last_spark = 0.0

        try:
            fuel = float(c.execute("SELECT value FROM generator_state WHERE key='current_fuel'").fetchone()[0])
        except (TypeError, ValueError):
            fuel = 0.0
        
        try:
            active_shift = c.execute("SELECT value FROM generator_state WHERE key='active_shift'").fetchone()[0]
        except (TypeError, IndexError):
            active_shift = "none"
            
        return {
            "status": status, 
            "start_time": start_time,
            "start_date": start_date,
            "total_hours": total, 
            "last_oil": last_oil,
            "last_spark": last_spark,
            "current_fuel": fuel,
            "active_shift": active_shift
        }

def get_today_completed_shifts():
    date_str = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        query = "SELECT event_type FROM logs WHERE timestamp LIKE ? AND event_type IN ('m_end', 'd_end', 'e_end', 'x_end')"
        rows = conn.execute(query, (f"{date_str}%",)).fetchall()
    
    completed = set()
    for r in rows:
        evt = r[0] 
        if "_" in evt:
            completed.add(evt.split("_")[0])
    return completed

def update_fuel(liters_delta):
    try:
        with get_connection() as conn:
            try:
                cur = float(conn.execute("SELECT value FROM generator_state WHERE key='current_fuel'").fetchone()[0])
            except (TypeError, ValueError):
                cur = 0.0
            
            new_val = cur + liters_delta
            if new_val < 0:
                new_val = 0
            conn.execute("UPDATE generator_state SET value = ? WHERE key='current_fuel'", (str(new_val),))
            return new_val
    except Exception as e:
        logging.error(f"Помилка оновлення палива: {e}")
        return 0.0

def add_log(event, user, val=None, driver=None):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute("INSERT INTO logs (event_type, timestamp, user_name, value, driver_name) VALUES (?,?,?,?,?)",
                     (event, ts, user, val, driver))

def get_unsynced():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM logs WHERE is_synced = 0").fetchall()

def mark_synced(ids):
    """Позначає записи як синхронізовані. ВИПРАВЛЕНО SQL injection."""
    if not ids:
        return
    try:
        with get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f"UPDATE logs SET is_synced = 1 WHERE id IN ({placeholders})", ids)
    except Exception as e:
        logging.error(f"Помилка позначення синхронізованих: {e}")

def get_logs_for_period(start_date, end_date):
    with get_connection() as conn:
        query = """
            SELECT event_type, timestamp, user_name, value, driver_name 
            FROM logs 
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """
        return conn.execute(query, (start_date + " 00:00:00", end_date + " 23:59:59")).fetchall()

# --- MAINTENANCE ---
def update_hours(h):
    with get_connection() as conn:
        cur = float(conn.execute("SELECT value FROM generator_state WHERE key='total_hours'").fetchone()[0])
        conn.execute("UPDATE generator_state SET value = ? WHERE key='total_hours'", (str(cur + h),))

def set_total_hours(new_val):
    with get_connection() as conn:
        conn.execute("UPDATE generator_state SET value = ? WHERE key='total_hours'", (str(new_val),))

def record_maintenance(action, admin):
    date = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        cur = float(conn.execute("SELECT value FROM generator_state WHERE key='total_hours'").fetchone()[0])
        conn.execute("INSERT INTO maintenance (date, type, hours, admin) VALUES (?,?,?,?)", (date, action, cur, admin))
        if action == "oil":
            conn.execute("UPDATE generator_state SET value = ? WHERE key='last_oil_change'", (str(cur),))
        elif action == "spark":
            conn.execute("UPDATE generator_state SET value = ? WHERE key='last_spark_change'", (str(cur),))

# --- SCHEDULE ---
def toggle_schedule(date_str, hour):
    with get_connection() as conn:
        cur = conn.execute("SELECT is_off FROM schedule WHERE date = ? AND hour = ?", (date_str, hour)).fetchone()
        new_val = 0 if cur and cur[0] == 1 else 1
        if cur:
            conn.execute("UPDATE schedule SET is_off = ? WHERE date = ? AND hour = ?", (new_val, date_str, hour))
        else:
            conn.execute("INSERT INTO schedule (date, hour, is_off) VALUES (?, ?, 1)", (date_str, hour))
    return new_val

def set_schedule_range(date_str, start_h, end_h):
    with get_connection() as conn:
        for h in range(start_h, end_h):
            if 0 <= h < 24:
                conn.execute("INSERT OR REPLACE INTO schedule (date, hour, is_off) VALUES (?, ?, 1)", (date_str, h))

def get_schedule(date_str):
    with get_connection() as conn:
        rows = dict(conn.execute("SELECT hour, is_off FROM schedule WHERE date = ?", (date_str,)).fetchall())
    return {h: rows.get(h, 0) for h in range(24)}
