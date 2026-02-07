from __future__ import annotations

from datetime import datetime

import config


def now_kiev() -> datetime:
    """Повертає поточний час у таймзоні Europe/Kyiv (config.KYIV)."""
    return datetime.now(config.KYIV)


def format_hours_hhmm(hours_float: float) -> str:
    """Конвертує години (float) у формат ГГ:ХХ. Підтримує від'ємні значення."""
    try:
        h = float(hours_float)
    except Exception:
        h = 0.0

    sign = "-" if h < 0 else ""
    h = abs(h)

    total_minutes = int(round(h * 60.0))
    hh = total_minutes // 60
    mm = total_minutes % 60

    return f"{sign}{hh:02d}:{mm:02d}"
