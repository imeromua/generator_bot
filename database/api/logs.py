import logging
from datetime import datetime

import config
from database.models import get_connection, begin_transaction
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
    """Повертає останні N подій у хронології за часом (новіші → старіші).

    Використовує ORDER BY timestamp DESC, id DESC, щоб коректно показувати
    хронологію навіть після імпорту старих подій (коли id >, але дата <).
    """
    try:
        lim = int(limit)
    except Exception:
        lim = 15

    if lim <= 0:
        lim = 15

    with get_connection() as conn:
        query = """
            SELECT event_type, timestamp, user_name, value, driver_name, receipt_number
            FROM logs
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
        """
        return conn.execute(query, (lim,)).fetchall()


def add_log(event, user, val=None, driver=None, receipt=None, ts: str | None = None, conn=None):
    """FIX #7: Add optional conn parameter for transactional operations.
    
    Додає подію в журнал. Тепер підтримує receipt_number.
    
    Args:
        event: Event type
        user: User name
        val: Optional value
        driver: Optional driver name
        receipt: Optional receipt number
        ts: Optional timestamp (defaults to now)
        conn: Optional existing connection for atomic operations with state changes
    """
    ts_val = ts or datetime.now(config.KYIV).strftime("%Y-%m-%d %H:%M:%S")
    
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    
    try:
        conn.execute(
            "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
            (event, ts_val, user, val, driver, receipt),
        )
    finally:
        if close_conn:
            try:
                conn.close()
            except Exception:
                pass


def try_start_shift(event_type: str, user_name: str, dt: datetime) -> dict:
    """Атомарний старт зміни: тільки перший виграє (CAS по status OFF->ON)."""
    ts = dt.strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        try:
            begin_transaction(conn)

            # self-heal мінімальних ключів, якщо state частково відсутній
            _conn_set_state_value(conn, "status", _conn_get_state_value(conn, "status", "OFF") or "OFF")
            _conn_set_state_value(conn, "active_shift", _conn_get_state_value(conn, "active_shift", "none") or "none")
            _conn_set_state_value(conn, "last_start_time", _conn_get_state_value(conn, "last_start_time", "") or "")
            _conn_set_state_value(conn, "last_start_date", _conn_get_state_value(conn, "last_start_date", "") or "")

            cur = conn.execute(
                "UPDATE generator_state SET value = 'ON' WHERE key = 'status' AND value = 'OFF'"
            )
            if cur.rowcount == 0:
                # FIX #5: Remove early commit - we haven't modified anything if CAS failed
                # Just rollback and return error
                active = _conn_get_state_value(conn, "active_shift", "none")
                st_time = _conn_get_state_value(conn, "last_start_time", "")
                try:
                    conn.rollback()
                except Exception:
                    pass
                return {"ok": False, "reason": "already_on", "active_shift": active, "start_time": st_time}

            _conn_set_state_value(conn, "active_shift", event_type)
            _conn_set_state_value(conn, "last_start_time", dt.strftime("%H:%M"))
            _conn_set_state_value(conn, "last_start_date", dt.strftime("%Y-%m-%d"))

            # FIX #7: Use transactional add_log with existing connection
            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                (event_type, ts, user_name, None, None, None),
            )

            conn.commit()
            return {"ok": True, "ts": ts}

        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logging.error(f"try_start_shift error: {e}", exc_info=True)
            return {"ok": False, "reason": "error"}


def try_stop_shift(end_event_type: str, user_name: str, dt: datetime) -> dict:
    """Атомарне закриття зміни: тільки для активної зміни.
    
    FIX #6: Fuel consumption should be handled here atomically.
    This prevents TOCTOU race conditions between stop and scheduler.
    """
    ts = dt.strftime("%Y-%m-%d %H:%M:%S")
    expected_start = end_event_type.replace("_end", "_start")

    with get_connection() as conn:
        try:
            begin_transaction(conn)

            # self-heal мінімальних ключів
            _conn_set_state_value(conn, "status", _conn_get_state_value(conn, "status", "OFF") or "OFF")
            _conn_set_state_value(conn, "active_shift", _conn_get_state_value(conn, "active_shift", "none") or "none")

            status = _conn_get_state_value(conn, "status", "OFF")
            if status != "ON":
                try:
                    conn.rollback()
                except Exception:
                    pass
                return {"ok": False, "reason": "already_off"}

            active = _conn_get_state_value(conn, "active_shift", "none")
            if active != expected_start:
                try:
                    conn.rollback()
                except Exception:
                    pass
                return {"ok": False, "reason": "wrong_shift", "active_shift": active}

            # FIX #6: Calculate and apply fuel consumption atomically within this transaction
            # This prevents race conditions with scheduler or other concurrent operations
            try:
                start_time_str = _conn_get_state_value(conn, "last_start_time", "")
                if start_time_str:
                    from datetime import datetime as dt_lib
                    start_dt = dt_lib.strptime(start_time_str, "%H:%M")
                    duration_hours = (dt.hour * 60 + dt.minute - start_dt.hour * 60 - start_dt.minute) / 60.0
                    
                    if duration_hours > 0:
                        # Get fuel consumption rate from state or config
                        fuel_rate_str = _conn_get_state_value(conn, "fuel_consumption", str(config.FUEL_CONSUMPTION))
                        try:
                            fuel_rate = float(fuel_rate_str or config.FUEL_CONSUMPTION)
                        except Exception:
                            fuel_rate = config.FUEL_CONSUMPTION
                        
                        fuel_consumed = duration_hours * fuel_rate
                        
                        # Apply atomic fuel update
                        current_fuel = _conn_get_state_float(conn, "current_fuel", 0.0)
                        new_fuel = max(0.0, current_fuel - fuel_consumed)
                        _conn_set_state_value(conn, "current_fuel", str(new_fuel))
                        
                        logging.info(f"⛽ Fuel consumed during shift: {fuel_consumed:.2f}L (duration: {duration_hours:.2f}h, rate: {fuel_rate:.2f}L/h)")
            except Exception as e:
                logging.warning(f"⚠️ Failed to calculate fuel consumption in try_stop_shift: {e}")
                # Don't fail the entire shift stop if fuel calculation fails

            _conn_set_state_value(conn, "status", "OFF")
            _conn_set_state_value(conn, "active_shift", "none")

            # FIX #7: Use transactional add_log
            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                (end_event_type, ts, user_name, None, None, None),
            )

            conn.commit()
            return {"ok": True, "ts": ts}

        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logging.error(f"try_stop_shift error: {e}", exc_info=True)
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
            SELECT event_type, timestamp, user_name, value, driver_name, receipt_number
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
            SELECT timestamp, user_name, value, driver_name, receipt_number
            FROM logs
            WHERE event_type = 'refill' AND timestamp LIKE ?
            ORDER BY timestamp ASC
        """
        return conn.execute(query, (f"{date_str}%",)).fetchall()
