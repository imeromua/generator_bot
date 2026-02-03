import sqlite3

DB_NAME = "generator.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, full_name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS drivers (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, event_type TEXT, timestamp TEXT, user_name TEXT, value TEXT, driver_name TEXT, is_synced INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS generator_state (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS schedule (date TEXT, hour INTEGER, is_off INTEGER, PRIMARY KEY(date, hour))''')
    c.execute('''CREATE TABLE IF NOT EXISTS maintenance (id INTEGER PRIMARY KEY, date TEXT, type TEXT, hours REAL, admin TEXT)''')

    defaults = [
        ('total_hours', '0.0'),       
        ('last_oil_change', '0.0'),   
        ('status', 'OFF'),            
        ('last_start_time', ''),
        ('current_fuel', '0.0') # 👈 НОВЕ: Залишок палива
    ]
    for k, v in defaults:
        c.execute("INSERT OR IGNORE INTO generator_state (key, value) VALUES (?, ?)", (k, v))
    
    conn.commit()
    conn.close()
    print("✅ База даних ініціалізована.")