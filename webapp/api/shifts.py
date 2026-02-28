"""Shift schedule API endpoints."""
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
import database.db_api as db
from webapp.utils.validation import extract_user as _extract_user
from webapp.utils.permissions import is_admin as _is_admin

logger = logging.getLogger(__name__)


async def api_shifts_get(request: Request):
    """GET /api/shifts/schedule — get shift schedule for a month or date."""
    user = _extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        from database.api.shift_schedule import get_month_schedule, get_date_schedule, get_personnel_shift_counts

        date_param = request.query_params.get("date")
        month_param = request.query_params.get("month")  # YYYY-MM

        if date_param:
            entries = get_date_schedule(date_param)
            return {"shifts": entries}
        elif month_param:
            year, month = int(month_param[:4]), int(month_param[5:7])
            entries = get_month_schedule(year, month)
            counts = get_personnel_shift_counts(month_param)
            return {"shifts": entries, "personnel_counts": counts, "month": month_param}
        else:
            from utils.time import now_kiev

            now = now_kiev()
            month_str = now.strftime("%Y-%m")
            year, month = now.year, now.month
            entries = get_month_schedule(year, month)
            counts = get_personnel_shift_counts(month_str)
            return {"shifts": entries, "personnel_counts": counts, "month": month_str}
    except Exception as e:
        logger.exception("api_shifts_get error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_shifts_set(request: Request):
    """POST /api/shifts/schedule — create or update a shift assignment."""
    user = _extract_user(request)
    if not _is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    date = str(body.get("date", "")).strip()
    shift_type = str(body.get("shift_type", "")).strip()
    if not date or not shift_type:
        return JSONResponse(content={"error": "date та shift_type обов'язкові"}, status_code=400)

    try:
        from database.api.shift_schedule import upsert_shift, VALID_SHIFT_TYPES

        if shift_type not in VALID_SHIFT_TYPES:
            return JSONResponse(
                content={"error": f"shift_type має бути одним із: {', '.join(VALID_SHIFT_TYPES)}"}, status_code=400
            )

        upsert_shift(
            date=date,
            shift_type=shift_type,
            assigned_personnel_id=str(body.get("assigned_personnel_id", "")).strip() or None,
            status=str(body.get("status", "planned")).strip() or "planned",
            notes=str(body.get("notes", "")).strip() or None,
        )
        return {"ok": True, "message": "Зміну збережено"}
    except Exception as e:
        logger.exception("api_shifts_set error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_shifts_auto(request: Request):
    """POST /api/shifts/auto — generate auto schedule for a month."""
    user = _extract_user(request)
    if not _is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    month_param = str(body.get("month", "")).strip()
    save = bool(body.get("save", False))

    if not month_param or len(month_param) < 7:
        return JSONResponse(content={"error": "month (YYYY-MM) обов'язковий"}, status_code=400)

    try:
        from database.api.shift_schedule import auto_schedule_month, upsert_shift

        year, month = int(month_param[:4]), int(month_param[5:7])
        # Get personnel list from DB
        personnel_list = db.get_personnel_names()
        if not personnel_list:
            return JSONResponse(content={"error": "Персонал не знайдено. Додайте персонал спочатку."}, status_code=400)

        assignments = auto_schedule_month(year, month, personnel_list)

        if save:
            for a in assignments:
                upsert_shift(
                    date=a["date"],
                    shift_type=a["shift_type"],
                    assigned_personnel_id=a["assigned_personnel_id"],
                    status=a["status"],
                    notes=a["notes"],
                )

        return {
            "ok": True,
            "assignments": assignments,
            "saved": save,
            "message": f"Згенеровано {len(assignments)} змін" + (" та збережено" if save else " (попередній перегляд)"),
        }
    except Exception as e:
        logger.exception("api_shifts_auto error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_shifts_analytics(request: Request):
    """GET /api/shifts/analytics — shift load analytics."""
    user = _extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        from database.api.shift_schedule import get_personnel_shift_counts, get_month_schedule
        from utils.time import now_kiev

        now = now_kiev()
        month_str = request.query_params.get("month") or now.strftime("%Y-%m")
        year, month = int(month_str[:4]), int(month_str[5:7])

        counts = get_personnel_shift_counts(month_str)
        entries = get_month_schedule(year, month)

        # Status breakdown
        status_counts: dict = {}
        for e in entries:
            s = e.get("status", "planned")
            status_counts[s] = status_counts.get(s, 0) + 1

        return {
            "month": month_str,
            "total_shifts": len(entries),
            "personnel_counts": counts,
            "status_breakdown": status_counts,
        }
    except Exception as e:
        logger.exception("api_shifts_analytics error")
        return JSONResponse(content={"error": str(e)}, status_code=500)
