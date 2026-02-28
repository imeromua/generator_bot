import logging
from datetime import datetime

import config
from database.models import get_connection
from database.api.state import _conn_get_state_float, _conn_set_state_value

# FIX #11: Add maximum fuel capacity limit
MAX_FUEL_CAPACITY = 500.0  # Maximum reasonable fuel capacity in liters


def update_fuel(liters_delta, conn=None):
    """Update fuel with atomic SQL operation to prevent race conditions.

    FIX #10: Use SQL-level atomic update instead of read-modify-write pattern.
    This prevents lost updates in concurrent scenarios.

    FIX #11: Add maximum fuel capacity validation.

    Args:
        liters_delta: Amount to add (positive) or subtract (negative)
        conn: Optional existing connection for transactional operations

    Returns:
        New fuel value after update
    """
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    try:
        # FIX #10: Atomic update at SQL level using CASE to enforce bounds
        # This ensures read-modify-write happens atomically without races
        query = """
            UPDATE generator_state 
            SET value = CAST(
                CASE 
                    WHEN CAST(value AS REAL) + ? < 0 THEN 0.0
                    WHEN CAST(value AS REAL) + ? > ? THEN ?
                    ELSE CAST(value AS REAL) + ?
                END AS TEXT
            )
            WHERE key = 'current_fuel'
        """

        delta = float(liters_delta or 0.0)
        conn.execute(query, (delta, delta, MAX_FUEL_CAPACITY, MAX_FUEL_CAPACITY, delta))

        # Read back the new value
        new_val = _conn_get_state_float(conn, "current_fuel", 0.0)

        # Log if we hit limits
        if new_val == 0.0 and delta < 0:
            logging.info(f"⛽ Fuel update hit minimum (0.0L), delta was {delta:.2f}L")
        elif new_val == MAX_FUEL_CAPACITY and delta > 0:
            logging.warning(f"⛽ Fuel update hit maximum ({MAX_FUEL_CAPACITY}L), delta was {delta:.2f}L")

        return new_val

    except Exception as e:
        logging.error(f"Помилка оновлення палива: {e}")
        return 0.0
    finally:
        if close_conn:
            try:
                conn.close()
            except Exception:
                pass
