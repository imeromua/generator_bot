import logging
from datetime import datetime

import config
from database.models import get_connection
from database.api.state import _conn_get_state_float, _conn_set_state_value


def update_fuel(liters_delta):
    """Локальне паливо (state.current_fuel). Якщо таблиця еталон — бажано НЕ викликати це з хендлерів."""
    try:
        with get_connection() as conn:
            cur = _conn_get_state_float(conn, "current_fuel", 0.0)
            new_val = cur + float(liters_delta or 0.0)
            if new_val < 0:
                new_val = 0.0

            _conn_set_state_value(conn, "current_fuel", str(new_val))
            return new_val

    except Exception as e:
        logging.error(f"Помилка оновлення палива: {e}")
        return 0.0
