"""User management API endpoints."""
import logging
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

import config
import database.db_api as db
from webapp.utils import validation as _validation_mod
from webapp.utils import permissions as _permissions_mod
from webapp.utils.db_helpers import get_admin_info as _get_admin_info

logger = logging.getLogger(__name__)

_VALID_ROLES = list(config.ROLES.keys())


async def api_admin_users_list(request: Request):
    """GET /api/admin/users — список користувачів (лише для адмінів)."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    role = request.query_params.get("role", "").strip() or None
    is_active_str = request.query_params.get("is_active", "").strip()
    is_active: Optional[bool] = None
    if is_active_str == "true":
        is_active = True
    elif is_active_str == "false":
        is_active = False
    search = request.query_params.get("search", "").strip() or None
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(100, max(1, int(request.query_params.get("per_page", "20"))))
    except (TypeError, ValueError):
        per_page = 20

    try:
        users = db.get_users(role=role, is_active=is_active, search=search, page=page, per_page=per_page)
        total = db.count_users(role=role, is_active=is_active, search=search)
        return {"users": users, "total": total, "page": page, "per_page": per_page}
    except Exception as e:
        logger.exception("api_admin_users_list error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_admin_users_update_role(request: Request, user_id: int):
    """PUT /api/admin/users/{user_id}/role — змінити роль користувача."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    role = (body.get("role") or "").strip()
    if role not in _VALID_ROLES:
        return JSONResponse(content={"error": f"Невірна роль. Доступні: {', '.join(_VALID_ROLES)}"}, status_code=400)

    try:
        db_user = db.get_user(user_id)
        if not db_user:
            return JSONResponse(content={"error": "Користувача не знайдено"}, status_code=404)
        old_role = db_user[5] if len(db_user) > 5 else "user"
        db.update_user_role(user_id, role)
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name,
            "user_role_change",
            f"Змінено роль user {user_id}: {old_role} → {role}",
            target_entity=f"user:{user_id}",
            old_value=old_role,
            new_value=role,
        )
        return {"success": True, "message": f"Роль оновлено до {role}"}
    except Exception as e:
        logger.exception("api_admin_users_update_role error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_admin_users_block(request: Request, user_id: int):
    """PUT /api/admin/users/{user_id}/block — заблокувати користувача."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        body = {}

    reason = (body.get("reason") or "").strip() or None

    try:
        db_user = db.get_user(user_id)
        if not db_user:
            return JSONResponse(content={"error": "Користувача не знайдено"}, status_code=404)
        admin_id, admin_name = _get_admin_info(user)
        db.block_user(user_id, blocked_by=admin_id, reason=reason)
        db.log_admin_action(
            admin_id, admin_name,
            "user_block",
            f"Заблоковано user {user_id}" + (f": {reason}" if reason else ""),
            target_entity=f"user:{user_id}",
            new_value=reason,
        )
        return {"success": True, "message": "Користувача заблоковано"}
    except Exception as e:
        logger.exception("api_admin_users_block error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_admin_users_unblock(request: Request, user_id: int):
    """PUT /api/admin/users/{user_id}/unblock — розблокувати користувача."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    try:
        db_user = db.get_user(user_id)
        if not db_user:
            return JSONResponse(content={"error": "Користувача не знайдено"}, status_code=404)
        admin_id, admin_name = _get_admin_info(user)
        db.unblock_user(user_id)
        db.log_admin_action(
            admin_id, admin_name,
            "user_unblock",
            f"Розблоковано user {user_id}",
            target_entity=f"user:{user_id}",
        )
        return {"success": True, "message": "Користувача розблоковано"}
    except Exception as e:
        logger.exception("api_admin_users_unblock error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_admin_users_delete(request: Request, user_id: int):
    """DELETE /api/admin/users/{user_id} — soft-delete користувача."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    try:
        db_user = db.get_user(user_id)
        if not db_user:
            return JSONResponse(content={"error": "Користувача не знайдено"}, status_code=404)
        admin_id, admin_name = _get_admin_info(user)
        db.soft_delete_user(user_id)
        db.log_admin_action(
            admin_id, admin_name,
            "user_delete",
            f"Видалено (soft) user {user_id}",
            target_entity=f"user:{user_id}",
        )
        return {"success": True, "message": "Користувача видалено"}
    except Exception as e:
        logger.exception("api_admin_users_delete error")
        return JSONResponse(content={"error": str(e)}, status_code=500)
