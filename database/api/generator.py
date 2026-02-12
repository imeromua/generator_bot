"""Управління генераторами: основний та аварійний.

Підтримка двох генераторів:
- Основний (main): синхронізується з Google Sheets
- Аварійний (emergency): окремий облік, звіт в Excel

Спільне:
- Залишок палива (current_fuel)
- Персонал та водії

Індивідуальне:
- Мотогодини
- Витрати палива (л/год)
- ТО (мастило, свічки)
"""

import logging
from typing import Literal

from database.models import get_connection

logger = logging.getLogger(__name__)

GeneratorType = Literal["main", "emergency"]


def get_active_generator() -> GeneratorType:
    """Повертає активний генератор ('main' або 'emergency')."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM generator_state WHERE key='active_generator'")
    row = cur.fetchone()
    conn.close()
    
    if row and row[0] in ["main", "emergency"]:
        return row[0]
    return "main"  # дефолт


def switch_generator(target: GeneratorType, admin_name: str = "admin") -> tuple[bool, str]:
    """Перемикає на інший генератор.
    
    Перемикання можливе тільки коли генератор вимкнено (status=OFF).
    
    Args:
        target: 'main' або 'emergency'
        admin_name: ім'я адміна для логування
    
    Returns:
        (success: bool, message: str)
    """
    if target not in ["main", "emergency"]:
        return False, f"❌ Невірний тип генератора: {target}"
    
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        # Перевіримо статус
        cur.execute("SELECT value FROM generator_state WHERE key='status'")
        status_row = cur.fetchone()
        status = (status_row[0] if status_row else "OFF").upper()
        
        if status != "OFF":
            conn.close()
            return False, "⛔ Перемикання можливе тільки коли генератор вимкнено (OFF)"
        
        # Перевіримо поточний генератор
        cur.execute("SELECT value FROM generator_state WHERE key='active_generator'")
        current_row = cur.fetchone()
        current = current_row[0] if current_row else "main"
        
        if current == target:
            conn.close()
            gen_name = "Основний" if target == "main" else "Аварійний"
            return False, f"ℹ️ {gen_name} генератор вже активний"
        
        # Перемикаємо
        cur.execute(
            "INSERT OR REPLACE INTO generator_state (key, value) VALUES ('active_generator', ?)",
            (target,)
        )
        conn.commit()
        
        # Логуємо подію
        from_name = "Основний" if current == "main" else "Аварійний"
        to_name = "Основний" if target == "main" else "Аварійний"
        
        logger.info(f"🔄 {admin_name} перемкнув генератор: {from_name} → {to_name}")
        conn.close()
        
        return True, f"✅ Перемкнено на: {to_name} генератор"
    
    except Exception as e:
        logger.error(f"❌ Помилка перемикання генератора: {e}", exc_info=True)
        try:
            conn.close()
        except Exception:
            pass
        return False, f"❌ Помилка: {e}"


def get_generator_stats(gen_type: GeneratorType) -> dict:
    """Повертає статистику генератора.
    
    Args:
        gen_type: 'main' або 'emergency'
    
    Returns:
        {
            "total_hours": float,
            "last_oil_change": float,
            "last_spark_change": float,
        }
    """
    conn = get_connection()
    cur = conn.cursor()
    
    if gen_type == "main":
        keys = ["total_hours", "last_oil_change", "last_spark_change"]
    else:  # emergency
        keys = ["emergency_total_hours", "emergency_last_oil_change", "emergency_last_spark_change"]
    
    result = {}
    for key in keys:
        cur.execute("SELECT value FROM generator_state WHERE key=?", (key,))
        row = cur.fetchone()
        value = float(row[0]) if row and row[0] else 0.0
        
        # Нормалізуємо ключі для виводу
        if key.startswith("emergency_"):
            clean_key = key.replace("emergency_", "")
        else:
            clean_key = key
        
        result[clean_key] = value
    
    conn.close()
    return result


def update_generator_hours(gen_type: GeneratorType, hours_delta: float):
    """Додає мотогодини до генератора.
    
    Args:
        gen_type: 'main' або 'emergency'
        hours_delta: скільки годин додати
    """
    conn = get_connection()
    cur = conn.cursor()
    
    key = "total_hours" if gen_type == "main" else "emergency_total_hours"
    
    cur.execute("SELECT value FROM generator_state WHERE key=?", (key,))
    row = cur.fetchone()
    current = float(row[0]) if row and row[0] else 0.0
    
    new_value = current + hours_delta
    cur.execute(
        "INSERT OR REPLACE INTO generator_state (key, value) VALUES (?, ?)",
        (key, str(new_value))
    )
    conn.commit()
    conn.close()
    
    logger.info(f"⏱ {gen_type.upper()}: мотогодини {current:.2f} → {new_value:.2f} (+{hours_delta:.2f})")


def set_generator_hours(gen_type: GeneratorType, hours: float):
    """Встановлює абсолютне значення мотогодин.
    
    Args:
        gen_type: 'main' або 'emergency'
        hours: нове значення
    """
    conn = get_connection()
    key = "total_hours" if gen_type == "main" else "emergency_total_hours"
    conn.execute(
        "INSERT OR REPLACE INTO generator_state (key, value) VALUES (?, ?)",
        (key, str(hours))
    )
    conn.commit()
    conn.close()
    
    logger.info(f"⏱ {gen_type.upper()}: мотогодини встановлено: {hours:.2f}")


def update_generator_maintenance(
    gen_type: GeneratorType,
    maintenance_type: Literal["oil", "spark"],
    new_hours: float
):
    """Оновлює дані ТО генератора.
    
    Args:
        gen_type: 'main' або 'emergency'
        maintenance_type: 'oil' (мастило) або 'spark' (свічки)
        new_hours: мотогодини на мовлент заміни
    """
    conn = get_connection()
    
    if gen_type == "main":
        key = f"last_{maintenance_type}_change"
    else:
        key = f"emergency_last_{maintenance_type}_change"
    
    conn.execute(
        "INSERT OR REPLACE INTO generator_state (key, value) VALUES (?, ?)",
        (key, str(new_hours))
    )
    conn.commit()
    conn.close()
    
    maint_name = "мастила" if maintenance_type == "oil" else "свічок"
    logger.info(f"🛠 {gen_type.upper()}: Заміна {maint_name} на {new_hours:.2f} год")


def is_emergency_active() -> bool:
    """Перевіряє чи активний аварійний генератор."""
    return get_active_generator() == "emergency"


def get_generator_name(gen_type: GeneratorType) -> str:
    """Повертає людськочитабельне ім'я генератора."""
    return "🔋 Основний" if gen_type == "main" else "⚠️ Аварійний"
