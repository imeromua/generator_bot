"""Sheets access guard.

Controls whether Sheets API access is allowed.
"""

import database.db_api as db
import config


def sheets_forced_offline() -> bool:
    """Єдиний guard: якщо адмін увімкнув примусовий OFFLINE — в Sheets не ходимо.

    Додатково: якщо runtime інтеграція з Sheets вимкнена конфігом — теж не ходимо.

    Returns:
        True if Sheets access should be blocked
    """
    try:
        if not getattr(config, "SHEETS_RUNTIME_ENABLED", True):
            return True
        return bool(db.sheet_is_forced_offline())
    except Exception:
        return True
