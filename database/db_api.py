import sqlite3
import logging
import time
from datetime import datetime

import config
from database.models import get_connection

_OFFLINE_THRESHOLD_SECONDS = 24 * 60 * 60


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


# --- UI (single window) ---
def set_ui_message(user_id: int, chat_id: int, message_id: int):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_ui (user_id, chat_id, message_id) VALUES (?,?,?)",
            (int(user_id), int(chat_id), int(message_id))
        )


def get_ui_message(user_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT chat_id, message_id FROM user_ui WHERE user_id = ?",
            (int(user_id),)
        ).fetchone()
        return (row[0], row[1]) if row else None


def clear_ui_message(user_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM user_ui WHERE user_id = ?", (int(user_id),))


# --- PERSONNEL (mapping) ---
def set_personnel_for_user(user_id: int, personnel_name: str | None):
    """Призначає ПІБ (з колонки 'ПЕРСОНАЛ') для Telegram користувача."""
    with get_connection() as conn:
        if personnel_name is None or not str(personnel_name).strip():
            conn.execute("DELETE FROM user_personnel WHERE user_id = ?", (user_id,))
            return
        conn.execute(
            "INSERT OR REPLACE INTO user_personnel (user_id, personnel_name) VALUES (?, ?)",
            (int(user_id), str(personnel_name).strip())
        )


def get_personnel_for_user(user_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT personnel_name FROM user_personnel WHERE user_id = ?", (int(user_id),)).fetchone()
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


# --- PERSONNEL (list) ---
def sync_personnel_from_sheet(personnel_list):
    """Повністю оновлює список персоналу в базі на основі колонки AC з Таблиці."""
    if personnel_list is None:
        return

    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM personnel_names")
            for name in personnel_list:
                if name and str(name).strip():
                    conn.execute("INSERT OR IGNORE INTO personnel_names (name) VALUES (?)", (str(name).strip(),))
    except Exception as e:
        logging.error(f"Помилка синхронізації персоналу: {e}")


def get_personnel_names():
    with get_connection() as conn:
        return [r[0] for r in conn.execute("SELECT name FROM personnel_names ORDER BY name COLLATE NOCASE").fetchall()]


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
    """Повністю оновлює список водіїв у базі на основі списку з Таблиці."""
    if not driver_list:
        return

    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM drivers")
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
    """Безпечний set для generator_state (upsert)."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generator_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(key), str(value))
        )


def get_state_value(key: str, default=None):
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM generator_state WHERE key = ?", (str(key),)).fetchone()
        if not row or row[0] is None:
            return default
        return row[0]


def sheet_mark_ok(ts: int | None = None):
    """Позначає, що з'єднання з таблицею є, та скидає offline-стан."""
    now_ts = int(ts or time.time())
    try:
        set_state("sheet_last_ok_ts", str(now_ts))
        set_state("sheet_first_fail_ts", "")
        set_state("sheet_offline", "0")
        set_state("sheet_offline_since_ts", "")
    except Exception:
        pass


def sheet_mark_fail(ts: int | None = None):
    """Фіксує перший момент, коли таблиця стала недоступною (для відліку 24 год)."""
    now_ts = int(ts or time.time())
    try:
        first = str(get_state_value("sheet_first_fail_ts", "") or "").strip()
        if not first:
            set_state("sheet_first_fail_ts", str(now_ts))
    except Exception:
        pass


def sheet_force_offline(ts: int | None = None):
    """Примусово вмикає offline-режим (адмінська дія)."""
    now_ts = int(ts or time.time())
    try:
        # якщо перша помилка ще не зафіксована — ставимо, щоб було видно в адмінці
        first = str(get_state_value("sheet_first_fail_ts", "") or "").strip()
        if not first:
            set_state("sheet_first_fail_ts", str(now_ts))

        set_state("sheet_offline", "1")
        set_state("sheet_offline_since_ts", str(now_ts))
    except Exception:
        pass


def sheet_force_online(ts: int | None = None):
    """Примусово вимикає offline-режим (адмінська дія).

    ВАЖЛИВО: ми не ставимо sheet_last_ok_ts, бо це не гарантує доступність Sheets.
    """
    now_ts = int(ts or time.time())
    try:
        set_state("sheet_offline", "0")
        set_state("sheet_offline_since_ts", "")
        set_state("sheet_first_fail_ts", "")
    except Exception:
        pass


def sheet_check_offline(threshold_seconds: int = _OFFLINE_THRESHOLD_SECONDS) -> bool:
    """True якщо offline уже активний або якщо помилка доступу триває >= threshold_seconds."""
    try:
        if str(get_state_value("sheet_offline", "0") or "0").strip() == "1":
            return True

        first = str(get_state_value("sheet_first_fail_ts", "") or "").strip()
        if not first:
            return False

        first_ts = int(float(first))
        if (time.time() - first_ts) >= int(threshold_seconds):
            set_state("sheet_offline", "1")
            set_state("sheet_offline_since_ts", str(int(time.time())))
            return True

        return False

    except Exception:
        return False


def sheet_is_offline() -> bool:
    return bool(sheet_check_offline())


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
    date_str = datetime.now(config.KYIV).strftime("%Y-%m-%d")
    with get_connection() as conn:
        query = "SELECT event_type FROM logs WHERE timestamp LIKE ? AND event_type IN ('m_end', 'd_end', 'e_end', 'x_end')"
        rows = conn.execute(query, (f"{date_str}%",)).fetchall()

    completed = set()
    for r in rows:
        evt = r[0]
        if "_" in evt:
            completed.add(evt.split("_")[0])
    return completed


def get_last_logs(limit: int = 15):
    """Повертає останні N подій (новіші -> старіші)."""
    try:
        lim = int(limit)
    except Exception:
        lim = 15

    if lim <= 0:
        lim = 15

    with get_connection() as conn:
        query = """
            SELECT event_type, timestamp, user_name, value, driver_name
            FROM logs
            ORDER BY id DESC
            LIMIT ?
        """
        return conn.execute(query, (lim,)).fetchall()


def update_fuel(liters_delta):
    """Локальне паливо (state.current_fuel). Якщо таблиця еталон — бажано НЕ викликати це з хендлерів."""
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


def add_log(event, user, val=None, driver=None, ts: str | None = None):
    ts_val = ts or datetime.now(config.KYIV).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name) VALUES (?,?,?,?,?)",
            (event, ts_val, user, val, driver)
        )


def try_start_shift(event_type: str, user_name: str, dt: datetime) -> dict:
    """Атомарний старт зміни: тільки перший виграє (CAS по status OFF->ON)."""
    ts = dt.strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            cur = conn.execute(
                "UPDATE generator_state SET value = 'ON' WHERE key = 'status' AND value = 'OFF'"
            )
            if cur.rowcount == 0:
                active = conn.execute("SELECT value FROM generator_state WHERE key='active_shift'").fetchone()[0]
                st_time = conn.execute("SELECT value FROM generator_state WHERE key='last_start_time'").fetchone()[0]
                conn.commit()
                return {"ok": False, "reason": "already_on", "active_shift": active, "start_time": st_time}

            conn.execute("UPDATE generator_state SET value = ? WHERE key = 'active_shift'", (event_type,))
            conn.execute("UPDATE generator_state SET value = ? WHERE key = 'last_start_time'", (dt.strftime("%H:%M"),))
            conn.execute("UPDATE generator_state SET value = ? WHERE key = 'last_start_date'", (dt.strftime("%Y-%m-%d"),))

            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name) VALUES (?,?,?,?,?)",
                (event_type, ts, user_name, None, None)
            )

            conn.commit()
            return {"ok": True, "ts": ts}

        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logging.error(f"try_start_shift error: {e}")
            return {"ok": False, "reason": "error"}


def try_stop_shift(end_event_type: str, user_name: str, dt: datetime) -> dict:
    """Атомарне закриття зміни: тільки для активної зміни."""
    ts = dt.strftime("%Y-%m-%d %H:%M:%S")
    expected_start = end_event_type.replace("_end", "_start")

    with get_connection() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            status = conn.execute("SELECT value FROM generator_state WHERE key='status'").fetchone()[0]
            if status != "ON":
                conn.commit()
                return {"ok": False, "reason": "already_off"}

            active = conn.execute("SELECT value FROM generator_state WHERE key='active_shift'").fetchone()[0]
            if active != expected_start:
                conn.commit()
                return {"ok": False, "reason": "wrong_shift", "active_shift": active}

            conn.execute("UPDATE generator_state SET value = 'OFF' WHERE key = 'status'")
            conn.execute("UPDATE generator_state SET value = 'none' WHERE key = 'active_shift'")

            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name) VALUES (?,?,?,?,?)",
                (end_event_type, ts, user_name, None, None)
            )

            conn.commit()
            return {"ok": True, "ts": ts}

        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logging.error(f"try_stop_shift error: {e}")
            return {"ok": False, "reason": "error"}


def get_unsynced():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM logs WHERE is_synced = 0 ORDER BY id ASC").fetchall()


def mark_synced(ids):
    """Позначає записи як синхронізовані."""
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


def get_refills_for_date(date_str: str):
    """Повертає всі заправки за дату (для агрегації і idempotent sync у Sheet)."""
    if not date_str:
        return []
    with get_connection() as conn:
        query = """
            SELECT timestamp, user_name, value, driver_name
            FROM logs
            WHERE event_type = 'refill' AND timestamp LIKE ?
            ORDER BY timestamp ASC
        """
        return conn.execute(query, (f"{date_str}%",)).fetchall()


# --- MAINTENANCE ---
def update_hours(h):
    with get_connection() as conn:
        cur = float(conn.execute("SELECT value FROM generator_state WHERE key='total_hours'").fetchone()[0])
        conn.execute("UPDATE generator_state SET value = ? WHERE key='total_hours'", (str(cur + h),))


def set_total_hours(new_val):
    with get_connection() as conn:
        conn.execute("UPDATE generator_state SET value = ? WHERE key='total_hours'", (str(new_val),))


def record_maintenance(action, admin):
    date_s = datetime.now(config.KYIV).strftime("%Y-%m-%d")
    with get_connection() as conn:
        cur = float(conn.execute("SELECT value FROM generator_state WHERE key='total_hours'").fetchone()[0])
        conn.execute("INSERT INTO maintenance (date, type, hours, admin) VALUES (?,?,?,?)", (date_s, action, cur, admin))
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
