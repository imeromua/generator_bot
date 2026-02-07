from database.models import get_connection


def register_user(user_id, name):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, full_name) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name
            """,
            (user_id, name),
        )


def get_user(user_id):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def get_all_users():
    with get_connection() as conn:
        return conn.execute("SELECT user_id, full_name FROM users").fetchall()
