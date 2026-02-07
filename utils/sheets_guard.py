import database.db_api as db


def sheets_forced_offline() -> bool:
    """Єдиний guard: якщо адмін увімкнув примусовий OFFLINE — в Sheets не ходимо."""
    try:
        return bool(db.sheet_is_forced_offline())
    except Exception:
        return False
