"""Admin audit log database API.

Records all critical admin actions for accountability and auditability.
"""

import json
import logging
from datetime import datetime

import config
import database.models as db_models

logger = logging.getLogger(__name__)


def log_admin_action(
    admin_user_id: int,
    admin_name: str,
    action_type: str,
    action_description: str = "",
    target_entity: str = "",
    old_value=None,
    new_value=None,
    success: bool = True,
) -> None:
    """Write one row to admin_audit_log.

    Parameters
    ----------
    admin_user_id:
        Telegram user ID of the admin performing the action.
    admin_name:
        Display name of the admin.
    action_type:
        Short category key, e.g. ``fuel_set``, ``driver_add``, ``gen_switch``.
    action_description:
        Human-readable description of the action.
    target_entity:
        The object being changed (e.g. ``"driver:Іванов"``, ``"generator:main"``).
    old_value:
        Previous value (will be JSON-serialised if not already a string).
    new_value:
        New value (will be JSON-serialised if not already a string).
    success:
        Whether the action succeeded.
    """
    try:
        now = datetime.now(config.KYIV).strftime("%Y-%m-%d %H:%M:%S")

        def _to_json(v):
            if v is None:
                return None
            if isinstance(v, str):
                return v
            try:
                return json.dumps(v, ensure_ascii=False)
            except Exception:
                return str(v)

        old_json = _to_json(old_value)
        new_json = _to_json(new_value)
        success_int = 1 if success else 0

        conn = db_models.get_connection()
        try:
            conn.execute(
                """INSERT INTO admin_audit_log
                   (timestamp, admin_user_id, admin_name, action_type,
                    action_description, target_entity, old_value, new_value, success)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, admin_user_id, admin_name, action_type,
                 action_description, target_entity, old_json, new_json, success_int),
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"⚠️ Не вдалося записати аудит-лог: {e}")


def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    action_type: str = "",
    admin_user_id: int = 0,
    date_from: str = "",
    date_to: str = "",
) -> list:
    """Return audit log rows matching the given filters.

    Returns a list of tuples:
    (id, timestamp, admin_user_id, admin_name, action_type,
     action_description, target_entity, old_value, new_value, success)
    """
    try:
        conn = db_models.get_connection()
        try:
            conditions = []
            params = []

            if action_type:
                conditions.append("action_type = ?")
                params.append(action_type)
            if admin_user_id:
                conditions.append("admin_user_id = ?")
                params.append(admin_user_id)
            if date_from:
                conditions.append("timestamp >= ?")
                params.append(date_from)
            if date_to:
                # Include the entire day
                dt_end = date_to if len(date_to) > 10 else date_to + " 23:59:59"
                conditions.append("timestamp <= ?")
                params.append(dt_end)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            params.extend([limit, offset])

            cur = conn.cursor()
            cur.execute(
                f"""SELECT id, timestamp, admin_user_id, admin_name,
                           action_type, action_description, target_entity,
                           old_value, new_value, success
                    FROM admin_audit_log
                    {where}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?""",
                params,
            )
            return cur.fetchall()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"⚠️ Помилка отримання аудит-логів: {e}")
        return []


def count_audit_logs(
    action_type: str = "",
    admin_user_id: int = 0,
    date_from: str = "",
    date_to: str = "",
) -> int:
    """Return total count of audit log rows matching the given filters."""
    try:
        conn = db_models.get_connection()
        try:
            conditions = []
            params = []

            if action_type:
                conditions.append("action_type = ?")
                params.append(action_type)
            if admin_user_id:
                conditions.append("admin_user_id = ?")
                params.append(admin_user_id)
            if date_from:
                conditions.append("timestamp >= ?")
                params.append(date_from)
            if date_to:
                dt_end = date_to if len(date_to) > 10 else date_to + " 23:59:59"
                conditions.append("timestamp <= ?")
                params.append(dt_end)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM admin_audit_log {where}", params)
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"⚠️ Помилка підрахунку аудит-логів: {e}")
        return 0
