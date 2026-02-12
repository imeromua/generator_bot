"""FIX: Shift formatting utilities.

Профілактика дублювання "Зміна Зміна":
Функція shift_pretty() використовується для перетворення технічних кодів (m, d, e, x)
у користувацькі назви з емодзі.
"""


def shift_pretty(code_or_event: str) -> str:
    """Перетворює технічний код зміни у користувацьку назву з емодзі часу доби.

    Args:
        code_or_event: код зміни (m/d/e/x) або повна подія (m_start/d_end/тощо)

    Returns:
        Назва зміни з емодзі (наприклад "🌅 Зміна 1")

    Examples:
        >>> shift_pretty("m")
        "🌅 Зміна 1"
        >>> shift_pretty("m_start")
        "🌅 Зміна 1"
        >>> shift_pretty("d")
        "☀️ Зміна 2"
    """
    # Витягуємо код зміни (якщо це подія типу "m_start" - беремо тільки "m")
    code = code_or_event
    if "_" in code_or_event:
        code = code_or_event.split("_", 1)[0]

    # Емодзі часу доби для кращого відображення на всіх платформах
    return {
        "m": "🌅 Зміна 1",  # Ранок (morning)
        "d": "☀️ Зміна 2",  # День (day)
        "e": "🌙 Зміна 3",  # Вечір (evening)
        "x": "⚡ Екстра",   # Екстра зміна
    }.get(code, code_or_event)
