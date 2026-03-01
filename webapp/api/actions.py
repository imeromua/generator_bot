"""Action API endpoints (start, stop, refill)."""

import logging
from datetime import datetime
from fastapi import Request
from fastapi.responses import JSONResponse
import config
import database.db_api as db
from webapp.utils import validation as _validation_mod
from webapp.utils.db_helpers import atomic_transaction
from webapp.utils.time_helpers import _within_work_window

logger = logging.getLogger(__name__)


async def api_action_start(request: Request):
    """POST /api/action/start — старт зміни генератора."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    shift_code = (body.get("shift") or "").strip()
    if shift_code not in ("m", "d", "e", "x"):
        return JSONResponse(content={"error": "Невірний код зміни"}, status_code=400)

    user_id = int(user.get("id", 0))
    personnel = db.get_personnel_for_user(user_id)
    if not personnel:
        return JSONResponse(
            content={"error": "Нема прив'язки до персоналу. Зверніться до адміністратора."}, status_code=400
        )

    now = datetime.now(config.KYIV)

    # Перевірка робочого часу
    try:
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        end_t = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        if not _within_work_window(now.time(), start_t, end_t):
            return JSONResponse(
                content={"error": f"Заборонено поза робочим часом ({config.WORK_START_TIME}–{config.WORK_END_TIME})"},
                status_code=400,
            )
    except Exception:
        logger.warning("Не вдалося перевірити робочий час (конфіг?): пропускаємо перевірку")

    event_type = shift_code + "_start"
    res = db.try_start_shift(event_type, personnel, now)
    if not res.get("ok"):
        reason = res.get("reason", "error")
        if reason == "already_on":
            active = res.get("active_shift", "none")
            return JSONResponse(content={"error": f"Генератор вже працює (активна зміна: {active})"}, status_code=400)
        return JSONResponse(content={"error": "Помилка старту зміни"}, status_code=400)

    return {
        "ok": True,
        "message": f"Зміна запущена о {now.strftime('%H:%M')}",
        "shift": shift_code,
        "time": now.strftime("%H:%M"),
    }


async def api_action_stop(request: Request):
    """POST /api/action/stop — зупинка зміни генератора."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    shift_code = (body.get("shift") or "").strip()
    if shift_code not in ("m", "d", "e", "x"):
        return JSONResponse(content={"error": "Невірний код зміни"}, status_code=400)

    user_id = int(user.get("id", 0))
    personnel = db.get_personnel_for_user(user_id)
    if not personnel:
        return JSONResponse(
            content={"error": "Нема прив'язки до персоналу. Зверніться до адміністратора."}, status_code=400
        )

    now = datetime.now(config.KYIV)
    event_type = shift_code + "_end"
    res = db.try_stop_shift(event_type, personnel, now)
    if not res.get("ok"):
        reason = res.get("reason", "error")
        if reason == "already_off":
            return JSONResponse(content={"error": "Генератор вже вимкнено"}, status_code=400)
        if reason == "wrong_shift":
            active = res.get("active_shift", "none")
            return JSONResponse(content={"error": f"Зараз активна інша зміна: {active}"}, status_code=400)
        return JSONResponse(content={"error": "Помилка зупинки зміни"}, status_code=400)

    duration_hours = res.get("duration_hours", 0.0)
    fuel_consumed = res.get("fuel_consumed", 0.0)
    h = int(duration_hours)
    m = int((duration_hours - h) * 60)

    return {
        "ok": True,
        "message": f"Зміна закрита о {now.strftime('%H:%M')}",
        "shift": shift_code,
        "duration": f"{h:02d}:{m:02d}",
        "fuel_consumed": round(fuel_consumed, 1),
    }


async def api_action_refill(request: Request):
    """POST /api/action/refill — прийом палива."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    driver = (body.get("driver") or "").strip()
    receipt = (body.get("receipt") or "").strip()
    try:
        liters = float(body.get("liters", 0))
    except (TypeError, ValueError):
        return JSONResponse(content={"error": "Невірна кількість літрів"}, status_code=400)

    if not driver:
        return JSONResponse(content={"error": "Оберіть водія"}, status_code=400)
    if not receipt or len(receipt) > 50:
        return JSONResponse(content={"error": "Введіть коректний номер чека"}, status_code=400)
    if liters <= 0 or liters > 500:
        return JSONResponse(content={"error": "Кількість літрів має бути від 1 до 500"}, status_code=400)

    user_id = int(user.get("id", 0))
    personnel = db.get_personnel_for_user(user_id)
    if not personnel:
        return JSONResponse(
            content={"error": "Нема прив'язки до персоналу. Зверніться до адміністратора."}, status_code=400
        )

    # Перевірка робочого часу
    now = datetime.now(config.KYIV)
    try:
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        end_t = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        if not _within_work_window(now.time(), start_t, end_t):
            return JSONResponse(
                content={
                    "error": f"Прийом палива заборонено поза робочим часом ({config.WORK_START_TIME}–{config.WORK_END_TIME})"
                },
                status_code=400,
            )
    except Exception:
        logger.warning("Не вдалося перевірити робочий час (конфіг?): пропускаємо перевірку")

    try:
        with atomic_transaction() as conn:
            db.add_log("refill", personnel, str(liters), driver, receipt=receipt, conn=conn)
            db.update_fuel(liters, conn=conn)
    except Exception as e:
        logger.exception("api_action_refill error")
        return JSONResponse(content={"error": str(e)}, status_code=500)

    return {
        "ok": True,
        "message": f"Прийнято {liters:.1f} л палива (Водій: {driver}, Чек: {receipt})",
        "liters": liters,
        "driver": driver,
        "receipt": receipt,
    }
