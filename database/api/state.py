import time

import config
from database.models import get_connection

_OFFLINE_THRESHOLD_SECONDS = 24 * 60 * 60


def set_state(key, value):
    """Безпечний set для generator_state (upsert)."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generator_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(key), str(value)),
        )


def get_state_value(key: str, default=None):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM generator_state WHERE key = ?",
            (str(key),),
        ).fetchone()
        if not row or row[0] is None:
            return default
        return row[0]


def _conn_get_state_value(conn, key: str, default: str = "") -> str:
    """Читання generator_state в межах вже відкритого conn/транзакції."""
    try:
        row = conn.execute(
            "SELECT value FROM generator_state WHERE key = ?",
            (str(key),),
        ).fetchone()
        if not row or row[0] is None:
            return default
        return str(row[0])
    except Exception:
        return default


def _conn_set_state_value(conn, key: str, value: str):
    """Upsert generator_state в межах вже відкритого conn/транзакції."""
    try:
        conn.execute(
            """
            INSERT INTO generator_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(key), str(value)),
        )
    except Exception:
        # не валимо критичні операції, якщо state тимчасово битий
        pass


def _conn_get_state_float(conn, key: str, default: float = 0.0) -> float:
    v = _conn_get_state_value(conn, key, str(default))
    try:
        return float(v or 0.0)
    except Exception:
        return float(default)


def sheet_is_forced_offline() -> bool:
    """True якщо адмін примусово увімкнув OFFLINE (навіть якщо Sheets доступний)."""
    try:
        return str(get_state_value("sheet_offline_forced", "0") or "0").strip() == "1"
    except Exception:
        return False


def sheet_mark_ok(ts: int | None = None):
    """Позначає, що з'єднання з таблицею є.

    Якщо OFFLINE примусовий (sheet_offline_forced=1) — не вимикаємо його автоматично.
    """
    now_ts = int(ts or time.time())
    try:
        set_state("sheet_last_ok_ts", str(now_ts))
        if sheet_is_forced_offline():
            return
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
        set_state("sheet_offline_forced", "1")

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
    try:
        set_state("sheet_offline_forced", "0")
        set_state("sheet_offline", "0")
        set_state("sheet_offline_since_ts", "")
        set_state("sheet_first_fail_ts", "")
    except Exception:
        pass


def sheet_check_offline(threshold_seconds: int = _OFFLINE_THRESHOLD_SECONDS) -> bool:
    """FIX #8: Pure read operation without side effects.
    
    Returns True if offline is active (forced or auto) OR if access failure duration >= threshold.
    Does NOT modify database state - use sheet_mark_offline_if_needed() for that.
    
    This prevents unexpected mutations during what appears to be a read-only check.
    """
    try:
        if sheet_is_forced_offline():
            return True

        if str(get_state_value("sheet_offline", "0") or "0").strip() == "1":
            return True

        first = str(get_state_value("sheet_first_fail_ts", "") or "").strip()
        if not first:
            return False

        first_ts = int(float(first))
        if (time.time() - first_ts) >= int(threshold_seconds):
            # FIX #8: Don't modify state here - just report the condition
            return True

        return False

    except Exception:
        return False


def sheet_mark_offline_if_needed(threshold_seconds: int = _OFFLINE_THRESHOLD_SECONDS) -> bool:
    """FIX #8: Separate write operation to mark offline if threshold exceeded.
    
    Call this explicitly when you want to transition to offline state based on failure duration.
    Returns True if offline was marked, False otherwise.
    """
    try:
        if sheet_is_forced_offline():
            return True

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
    """Check if sheets is currently offline (read-only operation)."""
    return bool(sheet_check_offline())


def get_state():
    """Повертає поточний стан генератора.

    Робимо максимально "невбивно": якщо якихось ключів немає/БД частково зламана —
    повертаємо дефолти замість падіння IndexError/TypeError.
    """
    with get_connection() as conn:
        def _get(k: str, default: str = "") -> str:
            return _conn_get_state_value(conn, k, default)

        status = _get("status", "OFF")
        start_time = _get("last_start_time", "")
        start_date = _get("last_start_date", "")
        active_shift = _get("active_shift", "none")

        def _get_f(k: str, default: float = 0.0) -> float:
            return _conn_get_state_float(conn, k, default)

        total = _get_f("total_hours", 0.0)
        last_oil = _get_f("last_oil_change", 0.0)
        last_spark = _get_f("last_spark_change", 0.0)
        fuel = _get_f("current_fuel", 0.0)

        return {
            "status": status,
            "start_time": start_time,
            "start_date": start_date,
            "total_hours": total,
            "last_oil": last_oil,
            "last_spark": last_spark,
            "current_fuel": fuel,
            "active_shift": active_shift,
        }


# ========== ПІДТРИМКА ДВОХ ГЕНЕРАТОРІВ: ОСНОВНИЙ ТА АВАРІЙНИЙ ==========

def get_active_generator() -> str:
    """Повертає ID активного генератора: 'main' або 'emergency'."""
    return str(get_state_value("active_generator", "main") or "main").strip()


def set_active_generator(generator_id: str):
    """Встановлює активний генератор: 'main' або 'emergency'."""
    if generator_id not in ("main", "emergency"):
        raise ValueError(f"Invalid generator_id: {generator_id}. Must be 'main' or 'emergency'.")
    set_state("active_generator", generator_id)


def is_emergency_active() -> bool:
    """Перевіряє, чи активний аварійний генератор."""
    return get_active_generator() == "emergency"


def get_generator_state(generator_id: str | None = None):
    """Повертає стан конкретного генератора.
    
    Args:
        generator_id: 'main', 'emergency' або None (автовизначення активного)
    
    Returns:
        dict з полями: status, start_time, start_date, total_hours, last_oil, last_spark, current_fuel, active_shift
    """
    if generator_id is None:
        generator_id = get_active_generator()
    
    if generator_id == "main":
        # Основний генератор - стандартні ключі
        return get_state()
    
    elif generator_id == "emergency":
        # Аварійний генератор - окремі ключі, але спільний status/shift/fuel
        with get_connection() as conn:
            def _get(k: str, default: str = "") -> str:
                return _conn_get_state_value(conn, k, default)

            # Спільні параметри (статус, зміна, паливо)
            status = _get("status", "OFF")
            start_time = _get("last_start_time", "")
            start_date = _get("last_start_date", "")
            active_shift = _get("active_shift", "none")

            def _get_f(k: str, default: float = 0.0) -> float:
                return _conn_get_state_float(conn, k, default)

            # Окремі параметри аварійного генератора
            total = _get_f("emergency_total_hours", 0.0)
            last_oil = _get_f("emergency_last_oil_change", 0.0)
            last_spark = _get_f("emergency_last_spark_change", 0.0)
            
            # Паливо спільне
            fuel = _get_f("current_fuel", 0.0)

            return {
                "status": status,
                "start_time": start_time,
                "start_date": start_date,
                "total_hours": total,
                "last_oil": last_oil,
                "last_spark": last_spark,
                "current_fuel": fuel,
                "active_shift": active_shift,
            }
    
    else:
        raise ValueError(f"Unknown generator_id: {generator_id}")


def get_emergency_total_hours() -> float:
    """Повертає загальні мотогодини аварійного генератора."""
    try:
        return float(get_state_value("emergency_total_hours", "0.0") or 0.0)
    except Exception:
        return 0.0


def set_emergency_total_hours(hours: float):
    """Встановлює загальні мотогодини аварійного генератора."""
    set_state("emergency_total_hours", str(float(hours)))


def get_emergency_last_oil_change() -> float:
    """Повертає мотогодини при останній заміні мастила (аварійний)."""
    try:
        return float(get_state_value("emergency_last_oil_change", "0.0") or 0.0)
    except Exception:
        return 0.0


def set_emergency_last_oil_change(hours: float):
    """Встановлює мотогодини при останній заміні мастила (аварійний)."""
    set_state("emergency_last_oil_change", str(float(hours)))


def get_emergency_last_spark_change() -> float:
    """Повертає мотогодини при останній заміні свічок (аварійний)."""
    try:
        return float(get_state_value("emergency_last_spark_change", "0.0") or 0.0)
    except Exception:
        return 0.0


def set_emergency_last_spark_change(hours: float):
    """Встановлює мотогодини при останній заміні свічок (аварійний)."""
    set_state("emergency_last_spark_change", str(float(hours)))


def get_fuel_consumption_rate() -> float:
    """Повертає витрати палива для активного генератора (л/год).
    
    Основний: config.FUEL_CONSUMPTION
    Аварійний: config.EMERGENCY_FUEL_CONSUMPTION
    """
    if is_emergency_active():
        return float(getattr(config, "EMERGENCY_FUEL_CONSUMPTION", config.FUEL_CONSUMPTION))
    return float(config.FUEL_CONSUMPTION)
