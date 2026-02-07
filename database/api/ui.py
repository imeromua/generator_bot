from database.models import get_connection


def set_ui_message(user_id: int, chat_id: int, message_id: int):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_ui (user_id, chat_id, message_id) VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE
              SET chat_id = excluded.chat_id,
                  message_id = excluded.message_id
            """,
            (int(user_id), int(chat_id), int(message_id)),
        )


def get_ui_message(user_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT chat_id, message_id FROM user_ui WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        return (row[0], row[1]) if row else None


def clear_ui_message(user_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM user_ui WHERE user_id = ?", (int(user_id),))
