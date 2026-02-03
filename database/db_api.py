import sqlite3
from datetime import datetime
from database.models import DB_NAME

# --- USER ---
def register_user(user_id, name):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT OR REPLACE INTO users (user_id, full_name) VALUES (?, ?)", (user_id, name))

def get_user(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

def get_all_users():
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("SELECT user_id, full_name FROM users").fetchall()

# --- DRIVERS ---
def add_driver(name):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("INSERT INTO drivers (name) VALUES (?)", (name,))
        return True
    except: return False

def get_drivers():
    with sqlite3.connect(DB_NAME) as conn:
        return [r[0] for r in conn.execute("SELECT name FROM drivers").fetchall()]

def delete_driver(name):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM drivers WHERE name = ?", (name,))

# --- STATE & LOGS ---
def set_state(key, value):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE generator_state SET value = ? WHERE key = ?", (str(value), key))

def get_state():
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        status = c.execute("SELECT value FROM generator_state WHERE key='status'").fetchone()[0]
        start_time = c.execute("SELECT value FROM generator_state WHERE key='last_start_time'").fetchone()[0]
        total = float(c.execute("SELECT value FROM generator_state WHERE key='total_hours'").fetchone()[0])
        last_oil = float(c.execute("SELECT value FROM generator_state WHERE key='last_oil_change'").fetchone()[0])
        
        # Свічки (безпечне отримання)
        try:
            last_spark = float(c.execute("SELECT value FROM generator_state WHERE key='last_spark_change'").fetchone()[0])
        except: last_spark = 0.0

        # Паливо
        try:
            fuel = float(c.execute("SELECT value FROM generator_state WHERE key='current_fuel'").fetchone()[0])
        except: fuel = 0.0
            
        return {
            "status": status, 
            "start_time": start_time, 
            "total_hours": total, 
            "last_oil": last_oil,
            "last_spark": last_spark,
            "current_fuel": fuel
        }

def update_fuel(liters_delta):
    with sqlite3.connect(DB_NAME) as conn:
        try:
            cur = float(conn.execute("SELECT value FROM generator_state WHERE key='current_fuel'").fetchone()[0])
        except: cur = 0.0
        
        new_val = cur + liters_delta
        if new_val < 0: new_val = 0
        
        conn.execute("UPDATE generator_state SET value = ? WHERE key='current_fuel'", (str(new_val),))
        return new_val

def add_log(event, user, val=None, driver=None):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO logs (event_type, timestamp, user_name, value, driver_name) VALUES (?,?,?,?,?)",
                     (event, ts, user, val, driver))

def get_unsynced():
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("SELECT * FROM logs WHERE is_synced = 0").fetchall()

def mark_synced(ids):
    if not ids: return
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(f"UPDATE logs SET is_synced = 1 WHERE id IN ({','.join(map(str, ids))})")

def get_logs_for_period(start_date, end_date):
    with sqlite3.connect(DB_NAME) as conn:
        query = """
            SELECT event_type, timestamp, user_name, value, driver_name 
            FROM logs 
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """
        return conn.execute(query, (start_date + " 00:00:00", end_date + " 23:59:59")).fetchall()

# --- MAINTENANCE ---
def update_hours(h):
    with sqlite3.connect(DB_NAME) as conn:
        cur = float(conn.execute("SELECT value FROM generator_state WHERE key='total_hours'").fetchone()[0])
        conn.execute("UPDATE generator_state SET value = ? WHERE key='total_hours'", (str(cur + h),))

# 👇 НОВЕ: Ручне встановлення годин
def set_total_hours(new_val):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE generator_state SET value = ? WHERE key='total_hours'", (str(new_val),))

def record_maintenance(action, admin):
    date = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(DB_NAME) as conn:
        cur = float(conn.execute("SELECT value FROM generator_state WHERE key='total_hours'").fetchone()[0])
        conn.execute("INSERT INTO maintenance (date, type, hours, admin) VALUES (?,?,?,?)", (date, action, cur, admin))
        
        if action == "oil":
            conn.execute("UPDATE generator_state SET value = ? WHERE key='last_oil_change'", (str(cur),))
        elif action == "spark":
            conn.execute("UPDATE generator_state SET value = ? WHERE key='last_spark_change'", (str(cur),))

# --- SCHEDULE ---
def toggle_schedule(date_str, hour):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.execute("SELECT is_off FROM schedule WHERE date = ? AND hour = ?", (date_str, hour)).fetchone()
        new_val = 0 if cur and cur[0] == 1 else 1
        if cur:
            conn.execute("UPDATE schedule SET is_off = ? WHERE date = ? AND hour = ?", (new_val, date_str, hour))
        else:
            conn.execute("INSERT INTO schedule (date, hour, is_off) VALUES (?, ?, 1)", (date_str, hour))
    return new_val

def set_schedule_range(date_str, start_h, end_h):
    with sqlite3.connect(DB_NAME) as conn:
        for h in range(start_h, end_h):
            if 0 <= h < 24:
                conn.execute("INSERT OR REPLACE INTO schedule (date, hour, is_off) VALUES (?, ?, 1)", (date_str, h))

def get_schedule(date_str):
    with sqlite3.connect(DB_NAME) as conn:
        rows = dict(conn.execute("SELECT hour, is_off FROM schedule WHERE date = ?", (date_str,)).fetchall())
    return {h: rows.get(h, 0) for h in range(24)}