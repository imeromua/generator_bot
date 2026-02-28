"""Notification preferences API endpoints."""
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from webapp.utils import validation as _validation_mod

logger = logging.getLogger(__name__)


async def api_notifications_get(request: Request):
    """GET /api/notifications/preferences — get user notification preferences."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        from database.api.notifications import get_user_preferences, NOTIFICATION_TYPES

        user_id = int(user.get("id", 0))
        prefs = get_user_preferences(user_id)
        return {
            "preferences": prefs,
            "types": {k: {"label": v["label"], "category": v["category"]} for k, v in NOTIFICATION_TYPES.items()},
        }
    except Exception as e:
        logger.exception("api_notifications_get error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_notifications_set(request: Request):
    """POST /api/notifications/preferences — update user notification preference."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    notification_type = str(body.get("notification_type", "")).strip()
    enabled = body.get("enabled")
    quiet_hours_start = body.get("quiet_hours_start")
    quiet_hours_end = body.get("quiet_hours_end")

    if not notification_type:
        return JSONResponse(content={"error": "notification_type обов'язковий"}, status_code=400)

    try:
        from database.api.notifications import set_user_preference, NOTIFICATION_TYPES

        if notification_type not in NOTIFICATION_TYPES:
            return JSONResponse(content={"error": "Невідомий тип сповіщення"}, status_code=400)
        user_id = int(user.get("id", 0))
        set_user_preference(
            user_id,
            notification_type,
            bool(enabled) if enabled is not None else True,
            quiet_hours_start or None,
            quiet_hours_end or None,
        )
        return {"ok": True, "message": "Налаштування збережено"}
    except Exception as e:
        logger.exception("api_notifications_set error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_notifications_test(request: Request):
    """POST /api/notifications/test — send a test notification to the user."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    # This endpoint is informational — the actual bot send happens via the Telegram bot
    return {
        "ok": True,
        "message": "🔔 Тест сповіщень. Якщо ви бачите це в webapp — система працює.",
    }
