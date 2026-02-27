"""DB API for fuel_orders table (Task 6)."""
from database.models import get_connection

VALID_STATUSES = ("pending", "ordered", "confirmed", "delivered", "cancelled")


def create_order(
    created_at: str,
    amount_liters: float,
    requested_by: int | None = None,
    supplier: str | None = None,
    price: float | None = None,
    delivery_date: str | None = None,
    notes: str | None = None,
) -> int:
    """Create a new fuel order; return the new order id."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO fuel_orders
               (created_at, requested_by, amount_liters, status, supplier, price, delivery_date, notes)
               VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (created_at, requested_by, amount_liters, supplier, price, delivery_date, notes),
        )
        row = cur.execute("SELECT last_insert_rowid()").fetchone()
        return row[0] if row else -1


def get_order(order_id: int) -> dict | None:
    """Fetch a single order by id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, created_at, requested_by, amount_liters, status, supplier, price, delivery_date, notes "
            "FROM fuel_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def get_orders(status: str | None = None, limit: int = 50) -> list[dict]:
    """Fetch fuel orders, optionally filtered by status."""
    with get_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT id, created_at, requested_by, amount_liters, status, supplier, price, delivery_date, notes "
                "FROM fuel_orders WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, created_at, requested_by, amount_liters, status, supplier, price, delivery_date, notes "
                "FROM fuel_orders ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_order_status(order_id: int, status: str, notes: str | None = None) -> bool:
    """Update order status; return True if a row was updated."""
    if status not in VALID_STATUSES:
        return False
    with get_connection() as conn:
        if notes is not None:
            conn.execute(
                "UPDATE fuel_orders SET status = ?, notes = ? WHERE id = ?",
                (status, notes, order_id),
            )
        else:
            conn.execute(
                "UPDATE fuel_orders SET status = ? WHERE id = ?",
                (status, order_id),
            )
    return True


def update_order(
    order_id: int,
    supplier: str | None = None,
    price: float | None = None,
    delivery_date: str | None = None,
    status: str | None = None,
    notes: str | None = None,
) -> bool:
    """Update editable fields of an order."""
    updates = []
    params = []
    if supplier is not None:
        updates.append("supplier = ?")
        params.append(supplier)
    if price is not None:
        updates.append("price = ?")
        params.append(price)
    if delivery_date is not None:
        updates.append("delivery_date = ?")
        params.append(delivery_date)
    if status is not None and status in VALID_STATUSES:
        updates.append("status = ?")
        params.append(status)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)
    if not updates:
        return False
    params.append(order_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE fuel_orders SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
    return True


def get_fuel_consumption_stats(days: int = 30) -> dict:
    """Calculate average fuel consumption over the last N days from logs."""
    from utils.time import now_kiev
    from datetime import timedelta

    cutoff = (now_kiev() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        # refill events (positive fuel input)
        refill_rows = conn.execute(
            "SELECT value FROM logs WHERE event_type = 'refill' AND timestamp >= ? ORDER BY timestamp",
            (cutoff,),
        ).fetchall()
        # shift end events (we use these to compute consumption periods)
        shift_end_rows = conn.execute(
            "SELECT timestamp, value FROM logs "
            "WHERE event_type LIKE '%_end' AND timestamp >= ? ORDER BY timestamp",
            (cutoff,),
        ).fetchall()

    total_refilled = 0.0
    for r in refill_rows:
        try:
            total_refilled += float(r[0])
        except Exception:
            pass

    total_consumed = 0.0
    total_hours = 0.0
    for r in shift_end_rows:
        try:
            parts = (r[1] or "").split(",")
            if len(parts) >= 2:
                total_consumed += float(parts[0]) if parts[0] else 0
                total_hours += float(parts[1]) if parts[1] else 0
        except Exception:
            pass

    avg_rate = (total_consumed / total_hours) if total_hours > 0 else 0.0
    return {
        "days": days,
        "total_refilled": round(total_refilled, 1),
        "total_consumed": round(total_consumed, 1),
        "total_hours": round(total_hours, 1),
        "avg_rate_per_hour": round(avg_rate, 2),
    }


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "created_at": row[1],
        "requested_by": row[2],
        "amount_liters": row[3],
        "status": row[4],
        "supplier": row[5],
        "price": row[6],
        "delivery_date": row[7],
        "notes": row[8],
    }
