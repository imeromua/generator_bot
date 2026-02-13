"""Schedule management API.

Manages planned outage schedules by date and hour.
"""
from database.models import get_connection


def toggle_schedule(date_str: str, hour: int) -> int:
    """Toggle schedule state for a specific date and hour.

    Args:
        date_str: Date in YYYY-MM-DD format
        hour: Hour (0-23)

    Returns:
        New state: 1 if marked as off, 0 if marked as on
    """
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT is_off FROM schedule WHERE date = ? AND hour = ?",
            (date_str, hour),
        ).fetchone()
        new_val = 0 if cur and cur[0] == 1 else 1
        if cur:
            conn.execute(
                "UPDATE schedule SET is_off = ? WHERE date = ? AND hour = ?",
                (new_val, date_str, hour),
            )
        else:
            conn.execute(
                """
                INSERT INTO schedule (date, hour, is_off) VALUES (?, ?, 1)
                ON CONFLICT(date, hour) DO UPDATE SET is_off = excluded.is_off
                """,
                (date_str, hour),
            )
    return new_val


def set_schedule_range(date_str: str, start_h: int, end_h: int) -> None:
    """Mark a range of hours as off for a specific date.

    Args:
        date_str: Date in YYYY-MM-DD format
        start_h: Start hour (inclusive, 0-23)
        end_h: End hour (exclusive, 0-24)
    """
    with get_connection() as conn:
        for h in range(start_h, end_h):
            if 0 <= h < 24:
                conn.execute(
                    """
                    INSERT INTO schedule (date, hour, is_off) VALUES (?, ?, 1)
                    ON CONFLICT(date, hour) DO UPDATE SET is_off = excluded.is_off
                    """,
                    (date_str, h),
                )


def get_schedule(date_str: str) -> dict[int, int]:
    """Get full 24-hour schedule for a date.

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        Dictionary mapping hour (0-23) to state (0=on, 1=off)
    """
    with get_connection() as conn:
        rows = dict(
            conn.execute(
                "SELECT hour, is_off FROM schedule WHERE date = ?",
                (date_str,),
            ).fetchall()
        )
    return {h: rows.get(h, 0) for h in range(24)}
