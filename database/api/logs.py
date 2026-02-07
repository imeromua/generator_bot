import logging
from datetime import datetime

import config
from database.models import get_connection
from database.api.state import _conn_get_state_float, _conn_get_state_value, _conn_set_state_value


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


def add_log(event, user, val=None, driver=None, ts: str | None = None):
    ts_val = ts or datetime.now(config.KYIV).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name) VALUES (?,?,?,?,?)",
            (event, ts_val, user, val, driver),
        )


def try_start_shift(event_type: str, user_name: str, dt: datetime) -> dict:
    """Атомарний старт зміни: тільки перший виграє (CAS по status OFF->ON)."""
    ts = dt.strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            # self-heal мінімальних ключів, якщо state частково відсутній
            _conn_set_state_value(conn, "status", _conn_get_state_value(conn, "status", "OFF") or "OFF")
            _conn_set_state_value(conn, "active_shift", _conn_get_state_value(conn, "active_shift", "none") or "none")
            _conn_set_state_value(conn, "last_start_time", _conn_get_state_value(conn, "last_start_time", "") or "")
            _conn_set_state_value(conn, "last_start_date", _conn_get_state_value(conn, "last_start_date", "") or "")

            cur = conn.execute(
                "UPDATE generator_state SET value = 'ON' WHERE key = 'status' AND value = 'OFF'"
            )
            if cur.rowcount == 0:
                active = _conn_get_state_value(conn, "active_shift", "none")
                st_time = _conn_get_state_value(conn, "last_start_time", "")
                conn.commit()
                return {"ok": False, "reason": "already_on", "active_shift": active, "start_time": st_time}

            _conn_set_state_value(conn, "active_shift", event_type)
            _conn_set_state_value(conn, "last_start_time", dt.strftime("%H:%M"))
            _conn_set_state_value(conn, "last_start_date", dt.strftime("%Y-%m-%d"))

            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name) VALUES (?,?,?,?,?)",
                (event_type, ts, user_name, None, None),
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

            # self-heal мінімальних ключів
            _conn_set_state_value(conn, "status", _conn_get_state_value(conn, "status", "OFF") or "OFF")
            _conn_set_state_value(conn, "active_shift", _conn_get_state_value(conn, "active_shift", "none") or "none")

            status = _conn_get_state_value(conn, "status", "OFF")
            if status != "ON":
                conn.commit()
                return {"ok": False, "reason": "already_off"}

            active = _conn_get_state_value(conn, "active_shift", "none")
            if active != expected_start:
                conn.commit()
                return {"ok": False, "reason": "wrong_shift", "active_shift": active}

            _conn_set_state_value(conn, "status", "OFF")
            _conn_set_state_value(conn, "active_shift", "none")

            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name) VALUES (?,?,?,?,?)",
                (end_event_type, ts, user_name, None, None),
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
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE logs SET is_synced = 1 WHERE id IN ({placeholders})",
                ids,
            )
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
        return conn.execute(
            query,
            (start_date + " 00:00:00", end_date + " 23:59:59"),
        ).fetchall()


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
