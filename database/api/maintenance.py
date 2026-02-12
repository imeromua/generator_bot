import logging
from datetime import datetime

import config
from database.models import get_connection
from database.api.state import _conn_get_state_float, _conn_set_state_value, _conn_get_state_value


def update_hours(h, generator_id: str = "main"):
    """Оновити мотогодини генератора."""
    try:
        with get_connection() as conn:
            if generator_id == "emergency":
                cur = _conn_get_state_float(conn, "emergency_total_hours", 0.0)
                _conn_set_state_value(conn, "emergency_total_hours", str(cur + float(h or 0.0)))
            else:
                cur = _conn_get_state_float(conn, "total_hours", 0.0)
                _conn_set_state_value(conn, "total_hours", str(cur + float(h or 0.0)))
    except Exception as e:
        logging.error(f"Помилка update_hours: {e}")


def set_total_hours(new_val, generator_id: str = "main"):
    """Встановити загальні мотогодини генератора."""
    try:
        with get_connection() as conn:
            if generator_id == "emergency":
                _conn_set_state_value(conn, "emergency_total_hours", str(float(new_val or 0.0)))
            else:
                _conn_set_state_value(conn, "total_hours", str(float(new_val or 0.0)))
    except Exception as e:
        logging.error(f"Помилка set_total_hours: {e}")


def record_maintenance(action: str, admin: str, generator_id: str | None = None):
    """Записати виконання ТО та оновити лічильники.
    
    Args:
        action: Тип ТО - 'oil', 'spark', 'maintenance'
        admin: Ім'я адміністратора
        generator_id: ID генератора ('main', 'emergency' або None для активного)
    """
    date_s = datetime.now(config.KYIV).strftime("%Y-%m-%d %H:%M:%S")
    
    with get_connection() as conn:
        # Якщо generator_id не вказаний - беремо активний
        if generator_id is None:
            generator_id = _conn_get_state_value(conn, "active_generator", "main")
        
        # Отримуємо поточні мотогодини відповідного генератора
        if generator_id == "emergency":
            cur = _conn_get_state_float(conn, "emergency_total_hours", 0.0)
        else:
            cur = _conn_get_state_float(conn, "total_hours", 0.0)
        
        # Записуємо в таблицю maintenance
        conn.execute(
            "INSERT INTO maintenance (date, type, hours, admin, generator_id) VALUES (?,?,?,?,?)",
            (date_s, action, cur, admin, generator_id),
        )
        
        # Оновлюємо лічильники відповідного генератора
        if generator_id == "emergency":
            if action == "oil":
                _conn_set_state_value(conn, "emergency_last_oil_change", "0.0")
            elif action == "spark":
                _conn_set_state_value(conn, "emergency_last_spark_change", "0.0")
            elif action == "maintenance":
                # Планове ТО - скидаємо все
                _conn_set_state_value(conn, "emergency_last_oil_change", "0.0")
                _conn_set_state_value(conn, "emergency_last_spark_change", "0.0")
        else:
            if action == "oil":
                _conn_set_state_value(conn, "last_oil_change", "0.0")
            elif action == "spark":
                _conn_set_state_value(conn, "last_spark_change", "0.0")
            elif action == "maintenance":
                # Планове ТО - скидаємо все
                _conn_set_state_value(conn, "last_oil_change", "0.0")
                _conn_set_state_value(conn, "last_spark_change", "0.0")


def get_maintenance_history(generator_id: str | None = None, limit: int = 20):
    """Отримати історію ТО.
    
    Args:
        generator_id: Фільтр по генератору ('main', 'emergency' або None для всіх)
        limit: Максимальна кількість записів
    
    Returns:
        list: Список кортежів (id, date, type, hours, admin, generator_id)
    """
    with get_connection() as conn:
        if generator_id:
            query = """
                SELECT id, date, type, hours, admin, generator_id
                FROM maintenance
                WHERE generator_id = ?
                ORDER BY id DESC
                LIMIT ?
            """
            return conn.execute(query, (generator_id, limit)).fetchall()
        else:
            query = """
                SELECT id, date, type, hours, admin, generator_id
                FROM maintenance
                ORDER BY id DESC
                LIMIT ?
            """
            return conn.execute(query, (limit,)).fetchall()


def get_maintenance_stats(generator_id: str = "main"):
    """Отримати статистику ТО для генератора.
    
    Returns:
        dict: {
            'oil_needed': Скільки год до заміни мастила,
            'spark_needed': Скільки год до заміни свічок,
            'maintenance_needed': Скільки год до планового ТО,
            'total_hours': Загальні мотогодини,
            'last_oil': Мотогодин від останньої заміни мастила,
            'last_spark': Мотогодин від останньої заміни свічок,
        }
    """
    with get_connection() as conn:
        if generator_id == "emergency":
            total_hours = _conn_get_state_float(conn, "emergency_total_hours", 0.0)
            last_oil = _conn_get_state_float(conn, "emergency_last_oil_change", 0.0)
            last_spark = _conn_get_state_float(conn, "emergency_last_spark_change", 0.0)
        else:
            total_hours = _conn_get_state_float(conn, "total_hours", 0.0)
            last_oil = _conn_get_state_float(conn, "last_oil_change", 0.0)
            last_spark = _conn_get_state_float(conn, "last_spark_change", 0.0)
        
        # Розраховуємо скільки залишилось до кожного виду ТО
        oil_needed = config.OIL_CHANGE_INTERVAL - last_oil
        spark_needed = config.SPARK_CHANGE_INTERVAL - last_spark
        
        # Планове ТО - рахуємо від загальних мотогодин
        maintenance_needed = config.MAINTENANCE_INTERVAL - (total_hours % config.MAINTENANCE_INTERVAL)
        
        return {
            'oil_needed': max(0.0, oil_needed),
            'spark_needed': max(0.0, spark_needed),
            'maintenance_needed': max(0.0, maintenance_needed),
            'total_hours': total_hours,
            'last_oil': last_oil,
            'last_spark': last_spark,
        }


def get_next_maintenance_type(generator_id: str = "main"):
    """Визначає який вид ТО потрібен найближчим часом.
    
    Returns:
        tuple: (type, hours_left) або (None, None) якщо ТО не потрібно
    """
    stats = get_maintenance_stats(generator_id)
    
    # Знаходимо найближче ТО
    min_hours = None
    min_type = None
    
    if stats['oil_needed'] <= 0:
        return ('oil', 0)
    if stats['spark_needed'] <= 0:
        return ('spark', 0)
    if stats['maintenance_needed'] <= 0:
        return ('maintenance', 0)
    
    # Порівнюємо що ближче
    candidates = [
        ('oil', stats['oil_needed']),
        ('spark', stats['spark_needed']),
        ('maintenance', stats['maintenance_needed']),
    ]
    
    min_type, min_hours = min(candidates, key=lambda x: x[1])
    
    # Якщо до ТО залишилось менше 10 годин - попереджаємо
    if min_hours <= 10:
        return (min_type, min_hours)
    
    return (None, None)
