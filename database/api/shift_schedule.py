"""DB API for shift_schedule table (Task 8)."""
from database.models import get_connection

VALID_SHIFT_TYPES = ("m", "d", "e")  # morning, day, evening
VALID_STATUSES = ("planned", "confirmed", "completed", "cancelled")
SHIFT_LABELS = {"m": "🌅 Зміна 1", "d": "☀️ Зміна 2", "e": "🌙 Зміна 3"}


def upsert_shift(
    date: str,
    shift_type: str,
    assigned_personnel_id: str | None,
    status: str = "planned",
    notes: str | None = None,
) -> None:
    """Create or update a shift assignment."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO shift_schedule (date, shift_type, assigned_personnel_id, status, notes)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(date, shift_type) DO UPDATE SET
                 assigned_personnel_id = excluded.assigned_personnel_id,
                 status = excluded.status,
                 notes = excluded.notes
            """,
            (date, shift_type, assigned_personnel_id, status, notes),
        )


def get_shift(date: str, shift_type: str) -> dict | None:
    """Fetch a single shift assignment."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, date, shift_type, assigned_personnel_id, status, notes "
            "FROM shift_schedule WHERE date = ? AND shift_type = ?",
            (date, shift_type),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_month_schedule(year: int, month: int) -> list[dict]:
    """Fetch all shift assignments for a given month (YYYY-MM)."""
    prefix = f"{year:04d}-{month:02d}"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, date, shift_type, assigned_personnel_id, status, notes "
            "FROM shift_schedule WHERE date LIKE ? ORDER BY date, shift_type",
            (f"{prefix}%",),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_date_schedule(date: str) -> list[dict]:
    """Fetch all shift assignments for a specific date."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, date, shift_type, assigned_personnel_id, status, notes "
            "FROM shift_schedule WHERE date = ? ORDER BY shift_type",
            (date,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_shift_status(date: str, shift_type: str, status: str) -> bool:
    """Update status for a shift assignment."""
    if status not in VALID_STATUSES:
        return False
    with get_connection() as conn:
        conn.execute(
            "UPDATE shift_schedule SET status = ? WHERE date = ? AND shift_type = ?",
            (status, date, shift_type),
        )
    return True


def delete_shift(date: str, shift_type: str) -> None:
    """Remove a shift assignment."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM shift_schedule WHERE date = ? AND shift_type = ?",
            (date, shift_type),
        )


def get_personnel_schedule(personnel_name: str, month_prefix: str) -> list[dict]:
    """Fetch all shifts for a specific person in a month (YYYY-MM)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, date, shift_type, assigned_personnel_id, status, notes "
            "FROM shift_schedule WHERE assigned_personnel_id = ? AND date LIKE ? ORDER BY date, shift_type",
            (personnel_name, f"{month_prefix}%"),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_personnel_shift_counts(month_prefix: str) -> dict:
    """Count shifts per person for a given month."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT assigned_personnel_id, COUNT(*) FROM shift_schedule "
            "WHERE date LIKE ? AND status != 'cancelled' AND assigned_personnel_id IS NOT NULL "
            "GROUP BY assigned_personnel_id",
            (f"{month_prefix}%",),
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def auto_schedule_month(year: int, month: int, personnel_list: list[str]) -> list[dict]:
    """Generate auto schedule for a month with even load distribution.

    Returns list of assignments (not yet saved). Call upsert_shift() to persist.
    """
    import calendar
    from datetime import date as date_cls

    if not personnel_list:
        return []

    assignments = []
    _, days_in_month = calendar.monthrange(year, month)
    personnel_count = len(personnel_list)

    # Track consecutive night shifts per person to avoid overload
    last_night = {}  # person -> last date they had a night shift
    # Count shifts per person for even distribution
    shift_counts = {p: 0 for p in personnel_list}

    for day in range(1, days_in_month + 1):
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        for shift_idx, shift_type in enumerate(VALID_SHIFT_TYPES):
            # Pick person with fewest shifts, rotate based on day+shift_idx
            candidates = sorted(personnel_list, key=lambda p: (shift_counts[p], p))
            # Avoid giving same person consecutive night shifts (shift 'e')
            if shift_type == "e":
                candidates = [
                    p for p in candidates
                    if last_night.get(p) != f"{year:04d}-{month:02d}-{day - 1:02d}"
                ] or candidates
            chosen = candidates[0]
            assignments.append({
                "date": date_str,
                "shift_type": shift_type,
                "assigned_personnel_id": chosen,
                "status": "planned",
                "notes": None,
            })
            shift_counts[chosen] += 1
            if shift_type == "e":
                last_night[chosen] = date_str

    return assignments


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "date": row[1],
        "shift_type": row[2],
        "shift_label": SHIFT_LABELS.get(row[2], row[2]),
        "assigned_personnel_id": row[3],
        "status": row[4],
        "notes": row[5],
    }
