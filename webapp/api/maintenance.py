"""Maintenance and fuel management API endpoints."""

import logging
from fastapi import Request
from fastapi.responses import JSONResponse
import config
import database.db_api as db
from webapp.utils import validation as _validation_mod
from webapp.utils import permissions as _permissions_mod
from webapp.utils.db_helpers import get_admin_info as _get_admin_info

logger = logging.getLogger(__name__)


async def api_maintenance(request: Request):
    """GET /api/maintenance — стан технічного обслуговування.

    Query params:
        generator: 'main' | 'emergency' — який генератор показувати.
                   Якщо не вказано — використовується активний.
    """
    try:
        gen_param = (request.query_params.get("generator") or "").strip()
        if gen_param in ("main", "emergency"):
            active_gen = gen_param
        else:
            active_gen = db.get_active_generator()
        stats = db.get_maintenance_stats(active_gen)
        history = db.get_maintenance_history(active_gen, 10)

        history_list = []
        for row in history:
            history_list.append(
                {
                    "id": row[0] if len(row) > 0 else None,
                    "date": row[1] if len(row) > 1 else "",
                    "type": row[2] if len(row) > 2 else "",
                    "hours": row[3] if len(row) > 3 else 0,
                    "admin": row[4] if len(row) > 4 else "",
                }
            )

        # Додаємо інтервали ТО з конфігурації для прогрес-барів
        stats["oil_interval"] = config.OIL_CHANGE_INTERVAL
        stats["spark_interval"] = config.SPARK_CHANGE_INTERVAL
        stats["maintenance_interval"] = config.MAINTENANCE_INTERVAL

        return {
            "generator": active_gen,
            "stats": stats,
            "history": history_list,
        }
    except Exception as e:
        logger.exception("api_maintenance error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_maintenance_perform(request: Request):
    """POST /api/maintenance/perform — виконання технічного обслуговування."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    action = (body.get("action") or "").strip()
    generator_id = (body.get("generator") or "main").strip()

    if action not in ("oil", "spark", "maintenance"):
        return JSONResponse(content={"error": "Невірний тип ТО (oil, spark, maintenance)"}, status_code=400)
    if generator_id not in ("main", "emergency"):
        return JSONResponse(content={"error": "Невірний генератор"}, status_code=400)

    user_id = int(user.get("id", 0))
    user_info = db.get_user(user_id)
    actor = user_info[1] if user_info else user.get("first_name", "Адмін")

    try:
        db.record_maintenance(action, actor, generator_id)
        action_names = {"oil": "Заміна мастила", "spark": "Заміна свічок", "maintenance": "Планове ТО"}
        db.log_admin_action(
            user_id,
            actor,
            "maintenance_perform",
            f"{action_names.get(action, action)} на генераторі {generator_id}",
            target_entity=f"generator:{generator_id}",
            new_value={"action": action, "generator": generator_id},
        )
        return {
            "ok": True,
            "message": f"{action_names.get(action, action)} виконано",
        }
    except Exception as e:
        logger.exception("api_maintenance_perform error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_maintenance_set_hours(request: Request):
    """POST /api/maintenance/set-hours — встановлення мотогодин генератора."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    generator_id = (body.get("generator") or "main").strip()
    try:
        hours = float(body.get("hours", -1))
    except (TypeError, ValueError):
        return JSONResponse(content={"error": "Невірне значення мотогодин"}, status_code=400)

    if generator_id not in ("main", "emergency"):
        return JSONResponse(content={"error": "Невірний генератор"}, status_code=400)
    if hours < 0 or hours > 100000:
        return JSONResponse(
            content={"error": "Значення мотогодин поза допустимим діапазоном (0–100000)"}, status_code=400
        )

    try:
        old_stats = db.get_generator_stats(generator_id)
        old_hours = float(old_stats.get("total_hours", 0))
        db.set_total_hours(hours, generator_id)
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id,
            admin_name,
            "mnt_set_hours",
            f"Корекція мотогодин генератора {generator_id}: {old_hours:.1f} → {hours:.1f} год",
            target_entity=f"generator:{generator_id}",
            old_value=old_hours,
            new_value=hours,
        )
        return {
            "ok": True,
            "message": f"Мотогодини встановлено: {hours:.1f} год",
            "hours": hours,
        }
    except Exception as e:
        logger.exception("api_maintenance_set_hours error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_fuel_set(request: Request):
    """POST /api/fuel/set — встановлення поточного рівня палива (адмін)."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    try:
        fuel = float(body.get("fuel", -1))
    except (TypeError, ValueError):
        return JSONResponse(content={"error": "Невірне значення палива"}, status_code=400)

    if fuel < 0 or fuel > 10000:
        return JSONResponse(content={"error": "Значення палива поза допустимим діапазоном"}, status_code=400)

    try:
        old_state = db.get_state()
        old_fuel = float(old_state.get("current_fuel", 0))
        db.set_state("current_fuel", str(fuel))
        user_id = int(user.get("id", 0))
        user_info = db.get_user(user_id)
        actor = user_info[1] if user_info else user.get("first_name", "Адмін")
        db.add_log("corr_fuel_set", actor, str(fuel))
        db.log_admin_action(
            user_id,
            actor,
            "fuel_set",
            f"Корекція палива: {old_fuel:.1f} → {fuel:.1f} л",
            target_entity="fuel",
            old_value=old_fuel,
            new_value=fuel,
        )
        return {"ok": True, "message": f"Паливо встановлено: {fuel:.1f} л"}
    except Exception as e:
        logger.exception("api_fuel_set error")
        return JSONResponse(content={"error": str(e)}, status_code=500)
