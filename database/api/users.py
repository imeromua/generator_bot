from datetime import datetime

from database.models import get_connection


def register_user(user_id, name, username=None, first_name=None, last_name=None):
    """Register or update a user. Sets registered_at on first insert so the user
    appears correctly in the admin users list (sorted by registered_at DESC)."""
    ts = datetime.now().isoformat()
    full_name = name or str(user_id)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, full_name, username, first_name, last_name, registered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                full_name = excluded.full_name,
                username  = COALESCE(excluded.username, users.username),
                first_name = COALESCE(excluded.first_name, users.first_name),
                last_name  = COALESCE(excluded.last_name, users.last_name),
                registered_at = COALESCE(users.registered_at, excluded.registered_at)
            """,
            (user_id, full_name, username, first_name, last_name, ts),
        )


def get_user(user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ? AND deleted_at IS NULL",
            (user_id,),
        ).fetchone()


def get_all_users():
    with get_connection() as conn:
        return conn.execute("SELECT user_id, full_name FROM users").fetchall()


def create_user(
    user_id, username=None, first_name=None, last_name=None, role="user", is_active=True, registered_at=None
):
    """Create or update a user with full profile information."""
    if registered_at is None:
        registered_at = datetime.now().isoformat()
    elif hasattr(registered_at, "isoformat"):
        registered_at = registered_at.isoformat()
    full_name = " ".join(filter(None, [first_name, last_name])) or username or str(user_id)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, full_name, username, first_name, last_name, role, is_active, registered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                full_name  = excluded.full_name,
                username   = COALESCE(excluded.username, users.username),
                first_name = COALESCE(excluded.first_name, users.first_name),
                last_name  = COALESCE(excluded.last_name, users.last_name),
                registered_at = COALESCE(users.registered_at, excluded.registered_at)
            """,
            (user_id, full_name, username, first_name, last_name, role, 1 if is_active else 0, registered_at),
        )


def update_last_activity(user_id):
    """Update user's last activity timestamp."""
    ts = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE users SET last_activity = ? WHERE user_id = ?", (ts, user_id))


def get_users(role=None, is_active=None, search=None, page=1, per_page=20):
    """Return a list of users with optional filters and pagination.

    Sorts by registered_at DESC NULLS LAST so users without a registration
    timestamp still appear (they were registered via the old register_user
    that did not store registered_at).
    """
    conditions = ["deleted_at IS NULL"]
    params = []
    if role:
        conditions.append("role = ?")
        params.append(role)
    if is_active is not None:
        conditions.append("is_active = ?")
        params.append(1 if is_active else 0)
    if search:
        like = f"%{search}%"
        conditions.append("(username LIKE ? OR first_name LIKE ? OR last_name LIKE ? OR full_name LIKE ?)")
        params.extend([like, like, like, like])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * per_page
    params.extend([per_page, offset])
    # NULLS LAST — юзери без дати реєстрації все одно відображаються
    sql = (
        f"SELECT user_id, full_name, username, first_name, last_name, role, is_active, "
        f"registered_at, last_activity, blocked_at, blocked_by, block_reason "
        f"FROM users{where} "
        f"ORDER BY COALESCE(registered_at, '2099-01-01') DESC "
        f"LIMIT ? OFFSET ?"
    )
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_users(role=None, is_active=None, search=None):
    """Count users matching the given filters."""
    conditions = ["deleted_at IS NULL"]
    params = []
    if role:
        conditions.append("role = ?")
        params.append(role)
    if is_active is not None:
        conditions.append("is_active = ?")
        params.append(1 if is_active else 0)
    if search:
        like = f"%{search}%"
        conditions.append("(username LIKE ? OR first_name LIKE ? OR last_name LIKE ? OR full_name LIKE ?)")
        params.extend([like, like, like, like])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT COUNT(*) FROM users{where}"
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return row[0] if row else 0


def update_user_role(user_id, role):
    """Change a user's role."""
    with get_connection() as conn:
        conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))


def block_user(user_id, blocked_by=None, reason=None):
    """Block a user (set is_active=0)."""
    ts = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_active = 0, blocked_at = ?, blocked_by = ?, block_reason = ? WHERE user_id = ?",
            (ts, blocked_by, reason, user_id),
        )


def unblock_user(user_id):
    """Unblock a user (set is_active=1, clear block info)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_active = 1, blocked_at = NULL, blocked_by = NULL, block_reason = NULL WHERE user_id = ?",
            (user_id,),
        )


def soft_delete_user(user_id):
    """Soft-delete a user (set deleted_at timestamp)."""
    ts = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE users SET deleted_at = ? WHERE user_id = ?", (ts, user_id))


def _row_to_dict(row):
    """Convert a database row to a user dict."""
    if row is None:
        return None
    keys = [
        "user_id",
        "full_name",
        "username",
        "first_name",
        "last_name",
        "role",
        "is_active",
        "registered_at",
        "last_activity",
        "blocked_at",
        "blocked_by",
        "block_reason",
    ]
    d = {}
    for i, k in enumerate(keys):
        if i < len(row):
            d[k] = row[i]
        else:
            d[k] = None
    d["is_active"] = bool(d.get("is_active", 1))
    return d
