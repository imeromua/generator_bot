"""DB API for notification_preferences table (Task 5)."""
from database.models import get_connection

# Notification type categories
NOTIFICATION_TYPES = {
    # Critical (always on)
    "fuel_critical": {"label": "🔴 Паливо <15л", "category": "critical", "default": 1},
    "emergency_shutdown": {"label": "⚠️ Аварійне відключення", "category": "critical", "default": 1},
    "long_shift": {"label": "🛑 Зміна >9 годин", "category": "critical", "default": 1},
    "high_consumption": {"label": "🔥 Витрата >норми на 30%", "category": "critical", "default": 1},
    "gen_with_power": {"label": "⚡ Генератор при наявності світла", "category": "critical", "default": 1},
    # Important (configurable)
    "fuel_warning": {"label": "⚠️ Паливо <40л", "category": "important", "default": 1},
    "maintenance_soon": {"label": "🔧 ТО через <10 мотогодин", "category": "important", "default": 1},
    "shift_reminder": {"label": "📅 Нагадування про зміну (за 30 хв)", "category": "important", "default": 1},
    "fuel_received": {"label": "⛽ Паливо прийнято/витрачено", "category": "important", "default": 1},
    "generator_switched": {"label": "🔄 Генератор перемкнено", "category": "important", "default": 1},
    # Informational (optional)
    "shift_completed": {"label": "✅ Зміна завершена", "category": "info", "default": 0},
    "daily_report": {"label": "📊 Щоденний звіт", "category": "info", "default": 0},
    "weekly_report": {"label": "📈 Тижневий звіт", "category": "info", "default": 0},
    "achievement": {"label": "🎯 Досягнення", "category": "info", "default": 0},
}


def get_user_preferences(user_id: int) -> dict:
    """Return dict of notification_type -> enabled for user."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT notification_type, enabled, quiet_hours_start, quiet_hours_end, delivery_method "
            "FROM notification_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    prefs = {}
    for row in rows:
        prefs[row[0]] = {
            "enabled": bool(row[1]),
            "quiet_hours_start": row[2],
            "quiet_hours_end": row[3],
            "delivery_method": row[4] or "telegram",
        }
    # Fill defaults for missing types
    for ntype, meta in NOTIFICATION_TYPES.items():
        if ntype not in prefs:
            prefs[ntype] = {
                "enabled": bool(meta["default"]),
                "quiet_hours_start": None,
                "quiet_hours_end": None,
                "delivery_method": "telegram",
            }
    return prefs


def set_user_preference(
    user_id: int,
    notification_type: str,
    enabled: bool,
    quiet_hours_start: str | None = None,
    quiet_hours_end: str | None = None,
    delivery_method: str = "telegram",
) -> None:
    """Upsert a notification preference for a user."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO notification_preferences
               (user_id, notification_type, enabled, quiet_hours_start, quiet_hours_end, delivery_method)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, notification_type) DO UPDATE SET
                 enabled = excluded.enabled,
                 quiet_hours_start = excluded.quiet_hours_start,
                 quiet_hours_end = excluded.quiet_hours_end,
                 delivery_method = excluded.delivery_method
            """,
            (user_id, notification_type, int(enabled), quiet_hours_start, quiet_hours_end, delivery_method),
        )


def is_notification_enabled(user_id: int, notification_type: str) -> bool:
    """Check if a notification type is enabled for a user."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT enabled FROM notification_preferences WHERE user_id = ? AND notification_type = ?",
            (user_id, notification_type),
        ).fetchone()
    if row is not None:
        return bool(row[0])
    # Default based on type
    meta = NOTIFICATION_TYPES.get(notification_type, {})
    return bool(meta.get("default", 1))


def get_quiet_hours(user_id: int) -> tuple[str | None, str | None]:
    """Return (quiet_hours_start, quiet_hours_end) for a user (first non-null found)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT quiet_hours_start, quiet_hours_end FROM notification_preferences "
            "WHERE user_id = ? AND quiet_hours_start IS NOT NULL LIMIT 1",
            (user_id,),
        ).fetchone()
    if row:
        return row[0], row[1]
    return None, None


def set_quiet_hours(user_id: int, start: str | None, end: str | None) -> None:
    """Set quiet hours for all notification types of a user."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE notification_preferences SET quiet_hours_start = ?, quiet_hours_end = ? WHERE user_id = ?",
            (start, end, user_id),
        )
        # Also insert for any type that might not exist yet using a sentinel
        conn.execute(
            """INSERT OR IGNORE INTO notification_preferences
               (user_id, notification_type, enabled, quiet_hours_start, quiet_hours_end, delivery_method)
               VALUES (?, '_quiet_hours', 1, ?, ?, 'telegram')
            """,
            (user_id, start, end),
        )
        conn.execute(
            "UPDATE notification_preferences SET quiet_hours_start = ?, quiet_hours_end = ? "
            "WHERE user_id = ? AND notification_type = '_quiet_hours'",
            (start, end, user_id),
        )
