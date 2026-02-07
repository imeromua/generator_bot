import logging
from datetime import datetime

import config
from database.models import get_connection
from database.api.state import _conn_get_state_float, _conn_set_state_value


def update_hours(h):
    try:
        with get_connection() as conn:
            cur = _conn_get_state_float(conn, "total_hours", 0.0)
            _conn_set_state_value(conn, "total_hours", str(cur + float(h or 0.0)))
    except Exception as e:
        logging.error(f"Помилка update_hours: {e}")


def set_total_hours(new_val):
    try:
        with get_connection() as conn:
            _conn_set_state_value(conn, "total_hours", str(float(new_val or 0.0)))
    except Exception as e:
        logging.error(f"Помилка set_total_hours: {e}")


def record_maintenance(action, admin):
    date_s = datetime.now(config.KYIV).strftime("%Y-%m-%d")
    with get_connection() as conn:
        cur = _conn_get_state_float(conn, "total_hours", 0.0)
        conn.execute(
            "INSERT INTO maintenance (date, type, hours, admin) VALUES (?,?,?,?)",
            (date_s, action, cur, admin),
        )
        if action == "oil":
            _conn_set_state_value(conn, "last_oil_change", str(cur))
        elif action == "spark":
            _conn_set_state_value(conn, "last_spark_change", str(cur))
