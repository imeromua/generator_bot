import sqlite3
import logging

DB_NAME = "generator.db"


def get_connection():
    """Повертає з'єднання з БД з налаштуваннями для async"""
    return sqlite3.connect(DB_NAME, check_same_thread=False, timeout=10)


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, full_name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS drivers (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, event_type TEXT, timestamp TEXT, user_name TEXT, value TEXT, driver_name TEXT, is_synced INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS generator_state (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS schedule (date TEXT, hour INTEGER, is_off INTEGER, PRIMARY KEY(date, hour))''')
    c.execute('''CREATE TABLE IF NOT EXISTS maintenance (id INTEGER PRIMARY KEY, date TEXT, type TEXT, hours REAL, admin TEXT)''')

    # Прив'язка Telegram user_id -> ПІБ з колонки "ПЕРСОНАЛ"
    c.execute('''CREATE TABLE IF NOT EXISTS user_personnel (user_id INTEGER PRIMARY KEY, personnel_name TEXT)''')

    # Список персоналу (імпортуємо з таблиці, колонка AC)
    c.execute('''CREATE TABLE IF NOT EXISTS personnel_names (name TEXT PRIMARY KEY)''')

    # UI: "single window" — зберігаємо останнє повідомлення-дашборд
    c.execute('''CREATE TABLE IF NOT EXISTS user_ui (user_id INTEGER PRIMARY KEY, chat_id INTEGER, message_id INTEGER)''')

    defaults = [
        ('total_hours', '0.0'),
        ('last_oil_change', '0.0'),
        ('last_spark_change', '0.0'),
        ('status', 'OFF'),
        ('active_shift', 'none'),
        ('last_start_time', ''),
        ('last_start_date', ''),
        ('current_fuel', '0.0')
    ]
    for k, v in defaults:
        c.execute("INSERT OR IGNORE INTO generator_state (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()
    logging.info("✅ База даних ініціалізована.")
