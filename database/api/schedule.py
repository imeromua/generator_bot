from database.models import get_connection


def toggle_schedule(date_str, hour):
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
                "INSERT INTO schedule (date, hour, is_off) VALUES (?, ?, 1)",
                (date_str, hour),
            )
    return new_val


def set_schedule_range(date_str, start_h, end_h):
    with get_connection() as conn:
        for h in range(start_h, end_h):
            if 0 <= h < 24:
                conn.execute(
                    "INSERT OR REPLACE INTO schedule (date, hour, is_off) VALUES (?, ?, 1)",
                    (date_str, h),
                )


def get_schedule(date_str):
    with get_connection() as conn:
        rows = dict(
            conn.execute(
                "SELECT hour, is_off FROM schedule WHERE date = ?",
                (date_str,),
            ).fetchall()
        )
    return {h: rows.get(h, 0) for h in range(24)}
