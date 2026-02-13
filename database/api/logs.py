"""Shift logging and tracking API.

Manages generator operation logs, shift tracking, and fuel consumption.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Union
import sqlite3

import config
from database.models import get_connection, begin_transaction, ConnectionProxy
from database.api.state import _conn_get_state_float, _conn_get_state_value, _conn_set_state_value


def get_today_completed_shifts(generator_id: Optional[str] = None) -> set[str]:
    """Отримує завершені зміни за сьогодні.

    Args:
        generator_id: фільтр по генератору ('main', 'emergency' або None для всіх)

    Returns:
        Set of shift prefixes (m, d, e, x)
    """
    date_str = datetime.now(config.KYIV).strftime("%Y-%m-%d")
    with get_connection() as conn:
        if generator_id:
            query = "SELECT event_type FROM logs WHERE timestamp LIKE ? AND event_type IN ('m_end', 'd_end', 'e_end', 'x_end') AND generator_id = ?"
            rows = conn.execute(query, (f"{date_str}%", generator_id)).fetchall()
        else:
            query = "SELECT event_type FROM logs WHERE timestamp LIKE ? AND event_type IN ('m_end', 'd_end', 'e_end', 'x_end')"
            rows = conn.execute(query, (f"{date_str}%",)).fetchall()

    completed: set[str] = set()
    for r in rows:
        evt = r[0]
        if "_" in evt:
            completed.add(evt.split("_")[0])
    return completed


def get_last_logs(limit: int = 15, generator_id: Optional[str] = None) -> list[tuple]:
    """Повертає останні N подій у хронології за часом (новіші → старіші).

    Використовує ORDER BY timestamp DESC, id DESC, щоб коректно показувати
    хронологію навіть після імпорту старих подій (коли id >, але дата <).

    Args:
        limit: кількість подій
        generator_id: фільтр по генератору ('main', 'emergency' або None для всіх)

    Returns:
        List of tuples: (event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id)
    """
    try:
        lim = int(limit)
    except Exception:
        lim = 15

    if lim <= 0:
        lim = 15

    with get_connection() as conn:
        if generator_id:
            query = """
                SELECT event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id
                FROM logs
                WHERE generator_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
            """
            return conn.execute(query, (generator_id, lim)).fetchall()
        else:
            query = """
                SELECT event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id
                FROM logs
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
            """
            return conn.execute(query, (lim,)).fetchall()


def get_logs_page(limit: int = 15, offset: int = 0, generator_id: Optional[str] = None) -> list[tuple]:
    """Повертає події сторінками для пагінації.

    Сортування таке саме, як у get_last_logs: ORDER BY timestamp DESC, id DESC.

    Args:
        limit: розмір сторінки (кількість подій)
        offset: зміщення (скільки записів пропустити від початку)
        generator_id: фільтр по генератору ('main', 'emergency' або None для всіх)

    Returns:
        List of tuples: (event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id)
    """
    try:
        lim = int(limit)
    except Exception:
        lim = 15

    try:
        off = int(offset)
    except Exception:
        off = 0

    if lim <= 0:
        lim = 15
    if off < 0:
        off = 0

    with get_connection() as conn:
        if generator_id:
            query = """
                SELECT event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id
                FROM logs
                WHERE generator_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
            """
            return conn.execute(query, (generator_id, lim, off)).fetchall()
        else:
            query = """
                SELECT event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id
                FROM logs
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
            """
            return conn.execute(query, (lim, off)).fetchall()


def get_last_sync() -> tuple[Optional[str], Optional[str]]:
    """FIX #23: Повертає час останньої синхронізації та ім'я користувача.

    Returns:
        (timestamp_str, user_name) або (None, None) якщо синхронізації не було
    """
    with get_connection() as conn:
        query = """
            SELECT timestamp, user_name
            FROM logs
            WHERE event_type = 'sync'
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
        """
        row = conn.execute(query).fetchone()
        if row:
            return row[0], row[1]
        return None, None


def add_log(
    event: str,
    user: str,
    val: Optional[str] = None,
    driver: Optional[str] = None,
    receipt: Optional[str] = None,
    ts: Optional[str] = None,
    conn: Optional[Union[sqlite3.Connection, ConnectionProxy]] = None,
    generator_id: Optional[str] = None,
) -> None:
    """FIX #7: Add optional conn parameter for transactional operations.

    Додає подію в журнал. Тепер підтримує receipt_number та generator_id.

    Args:
        event: Event type
        user: User name
        val: Optional value
        driver: Optional driver name
        receipt: Optional receipt number
        ts: Optional timestamp (defaults to now)
        conn: Optional existing connection for atomic operations with state changes
        generator_id: Генератор ('main' або 'emergency'). Якщо None - визначається автоматично.
    """
    ts_val = ts or datetime.now(config.KYIV).strftime("%Y-%m-%d %H:%M:%S")

    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    # Якщо generator_id не вказаний - отримуємо поточний
    if generator_id is None:
        gen_id = _conn_get_state_value(conn, "active_generator", "main")
    else:
        gen_id = generator_id

    try:
        conn.execute(
            "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id) VALUES (?,?,?,?,?,?,?)",
            (event, ts_val, user, val, driver, receipt, gen_id),
        )
    finally:
        if close_conn:
            try:
                conn.close()
            except Exception:
                pass


def try_start_shift(event_type: str, user_name: str, dt: datetime) -> dict[str, any]:
    """Атомарний старт зміни: тільки перший виграє (CAS по status OFF->ON).

    Підтримка аварійного генератора: записує generator_id в лог.

    Args:
        event_type: Shift start event type (e.g., 'm_start', 'd_start')
        user_name: User initiating the shift
        dt: Shift start datetime

    Returns:
        Dict with keys: ok (bool), reason (if failed), ts, generator_id, active_shift, start_time
    """
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

            # Отримуємо поточний генератор
            generator_id = _conn_get_state_value(conn, "active_generator", "main")

            # Записуємо лог з generator_id
            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id) VALUES (?,?,?,?,?,?,?)",
                (event_type, ts, user_name, None, None, None, generator_id),
            )

            conn.commit()
            return {"ok": True, "ts": ts, "generator_id": generator_id}

        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logging.error(f"try_start_shift error: {e}", exc_info=True)
            return {"ok": False, "reason": "error"}


def try_stop_shift(end_event_type: str, user_name: str, dt: datetime) -> dict[str, any]:
    """Атомарне закриття зміни: тільки для активної зміни.

    FIX #6: Fuel consumption handled here atomically.
    FIX #19: Hours update also done atomically within same transaction.
    Підтримка аварійного генератора:
    - Записує generator_id в лог
    - Використовує відповідні витрати палива (main або emergency)
    - Оновлює відповідні мотогодини та ТО

    Args:
        end_event_type: Shift end event type (e.g., 'm_end', 'd_end')
        user_name: User ending the shift
        dt: Shift end datetime

    Returns:
        Dict with keys: ok (bool), reason (if failed), ts, duration_hours, fuel_consumed, generator_id
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

            # Отримуємо поточний генератор
            generator_id = _conn_get_state_value(conn, "active_generator", "main")
            is_emergency = (generator_id == "emergency")

            # FIX #19: Calculate duration, fuel, and hours atomically
            duration_hours = 0.0
            fuel_consumed = 0.0

            try:
                start_time_str = _conn_get_state_value(conn, "last_start_time", "")
                start_date_str = _conn_get_state_value(conn, "last_start_date", "")

                if start_time_str:
                    # Build full start datetime
                    if start_date_str:
                        start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
                    else:
                        # Fallback: assume today
                        start_dt = datetime.strptime(f"{dt.date()} {start_time_str}", "%Y-%m-%d %H:%M")
                        # If current time is earlier than start time, shift was yesterday
                        if dt.time() < datetime.strptime(start_time_str, "%H:%M").time():
                            start_dt = start_dt - timedelta(days=1)

                    # FIX #18: Use localize() for proper timezone handling (DST aware)
                    try:
                        start_dt = config.KYIV.localize(start_dt)
                    except AttributeError:
                        # Fallback if KYIV doesn't have localize (not pytz)
                        start_dt = start_dt.replace(tzinfo=config.KYIV)

                    # Calculate duration
                    duration_hours = (dt - start_dt).total_seconds() / 3600.0

                    if duration_hours < 0 or duration_hours > 24:
                        logging.warning(f"⚠️ Invalid duration: {duration_hours:.2f}h, resetting to 0")
                        duration_hours = 0.0

                    if duration_hours > 0:
                        # Визначаємо витрати палива залежно від генератора
                        if is_emergency:
                            # Аварійний генератор - з config.EMERGENCY_FUEL_CONSUMPTION
                            fuel_rate = getattr(config, "EMERGENCY_FUEL_CONSUMPTION", config.FUEL_CONSUMPTION)
                        else:
                            # Основний генератор - з state або config.FUEL_CONSUMPTION
                            fuel_rate_str = _conn_get_state_value(conn, "fuel_consumption", str(config.FUEL_CONSUMPTION))
                            try:
                                fuel_rate = float(fuel_rate_str or config.FUEL_CONSUMPTION)
                                if fuel_rate <= 0:
                                    fuel_rate = config.FUEL_CONSUMPTION
                            except Exception:
                                fuel_rate = config.FUEL_CONSUMPTION

                        fuel_consumed = duration_hours * fuel_rate

                        # Оновлюємо мотогодини відповідного генератора
                        if is_emergency:
                            # Аварійний генератор
                            total_hours = _conn_get_state_float(conn, "emergency_total_hours", 0.0)
                            new_total = total_hours + duration_hours
                            _conn_set_state_value(conn, "emergency_total_hours", str(new_total))

                            # Оновлюємо ТО
                            last_oil = _conn_get_state_float(conn, "emergency_last_oil_change", 0.0)
                            last_spark = _conn_get_state_float(conn, "emergency_last_spark_change", 0.0)
                            _conn_set_state_value(conn, "emergency_last_oil_change", str(last_oil + duration_hours))
                            _conn_set_state_value(conn, "emergency_last_spark_change", str(last_spark + duration_hours))
                        else:
                            # Основний генератор
                            total_hours = _conn_get_state_float(conn, "total_hours", 0.0)
                            new_total = total_hours + duration_hours
                            _conn_set_state_value(conn, "total_hours", str(new_total))

                            # Оновлюємо ТО
                            last_oil = _conn_get_state_float(conn, "last_oil_change", 0.0)
                            last_spark = _conn_get_state_float(conn, "last_spark_change", 0.0)
                            _conn_set_state_value(conn, "last_oil_change", str(last_oil + duration_hours))
                            _conn_set_state_value(conn, "last_spark_change", str(last_spark + duration_hours))

                        # Оновлюємо спільний залишок палива
                        current_fuel = _conn_get_state_float(conn, "current_fuel", 0.0)
                        new_fuel = max(0.0, current_fuel - fuel_consumed)
                        _conn_set_state_value(conn, "current_fuel", str(new_fuel))

                        gen_name = "АВАРІЙНИЙ" if is_emergency else "ОСНОВНИЙ"
                        logging.info(
                            f"⛽ [{gen_name}] Shift closed: duration={duration_hours:.2f}h, "
                            f"fuel_consumed={fuel_consumed:.2f}L, rate={fuel_rate:.2f}L/h, "
                            f"total_hours={new_total:.2f}h"
                        )

            except Exception as e:
                logging.error(f"⚠️ Failed to calculate metrics in try_stop_shift: {e}", exc_info=True)
                # Don't fail the entire shift stop if calculation fails
                duration_hours = 0.0
                fuel_consumed = 0.0

            _conn_set_state_value(conn, "status", "OFF")
            _conn_set_state_value(conn, "active_shift", "none")

            # Записуємо лог з generator_id
            conn.execute(
                "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id) VALUES (?,?,?,?,?,?,?)",
                (end_event_type, ts, user_name, None, None, None, generator_id),
            )

            conn.commit()
            return {
                "ok": True,
                "ts": ts,
                "duration_hours": duration_hours,
                "fuel_consumed": fuel_consumed,
                "generator_id": generator_id,
            }

        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logging.error(f"try_stop_shift error: {e}", exc_info=True)
            return {"ok": False, "reason": "error"}


def get_unsynced() -> list[tuple]:
    """Повертає несинхронізовані записи ОСНОВНОГО генератора.

    Аварійний генератор НЕ синхронізується з Sheets.

    Returns:
        List of unsynced log tuples
    """
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM logs WHERE is_synced = 0 AND generator_id = 'main' ORDER BY id ASC"
        ).fetchall()


def mark_synced(ids: list[int]) -> None:
    """Позначає записи як синхронізовані.

    Args:
        ids: List of log IDs to mark as synced
    """
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


def get_logs_for_period(
    start_date: str,
    end_date: str,
    generator_id: Optional[str] = None
) -> list[tuple]:
    """Отримує логи за період.

    Args:
        start_date: початкова дата (YYYY-MM-DD)
        end_date: кінцева дата (YYYY-MM-DD)
        generator_id: фільтр по генератору ('main', 'emergency' або None для всіх)

    Returns:
        List of log tuples: (event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id)
    """
    with get_connection() as conn:
        if generator_id:
            query = """
                SELECT event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id
                FROM logs
                WHERE timestamp >= ? AND timestamp <= ? AND generator_id = ?
                ORDER BY timestamp ASC
            """
            return conn.execute(
                query,
                (start_date + " 00:00:00", end_date + " 23:59:59", generator_id),
            ).fetchall()
        else:
            query = """
                SELECT event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id
                FROM logs
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            """
            return conn.execute(
                query,
                (start_date + " 00:00:00", end_date + " 23:59:59"),
            ).fetchall()


def get_refills_for_date(date_str: str, generator_id: Optional[str] = None) -> list[tuple]:
    """Повертає всі заправки за дату (для агрегації і idempotent sync у Sheet).

    Args:
        date_str: дата у форматі YYYY-MM-DD
        generator_id: фільтр по генератору

    Returns:
        List of refill tuples: (timestamp, user_name, value, driver_name, receipt_number)
    """
    if not date_str:
        return []
    with get_connection() as conn:
        if generator_id:
            query = """
                SELECT timestamp, user_name, value, driver_name, receipt_number
                FROM logs
                WHERE event_type = 'refill' AND timestamp LIKE ? AND generator_id = ?
                ORDER BY timestamp ASC
            """
            return conn.execute(query, (f"{date_str}%", generator_id)).fetchall()
        else:
            query = """
                SELECT timestamp, user_name, value, driver_name, receipt_number
                FROM logs
                WHERE event_type = 'refill' AND timestamp LIKE ?
                ORDER BY timestamp ASC
            """
            return conn.execute(query, (f"{date_str}%",)).fetchall()
