"""Status, schedule, user, generator, and driver API endpoints."""

import logging
from datetime import datetime, timedelta
from fastapi import Request
from fastapi.responses import JSONResponse
import config
import database.db_api as db
from webapp.utils import validation as _validation_mod
from webapp.utils import permissions as _permissions_mod
from webapp.utils.db_helpers import get_admin_info as _get_admin_info
from webapp.utils.time_helpers import _within_work_window

logger = logging.getLogger(__name__)


async def api_status(request: Request):
    """GET /api/status — поточний стан генератора."""
    try:
        state = db.get_state()
        active_gen = db.get_active_generator()
        gen_name = db.get_generator_name(active_gen)
        completed = db.get_today_completed_shifts()
        fuel_rate = db.get_fuel_consumption_rate()

        # Оцінка палива під час роботи
        current_fuel = float(state.get("current_fuel") or 0.0)
        status = state.get("status", "OFF")
        estimated_fuel = current_fuel

        # Нові поля для вкладки Зміни
        operator_name = ""
        shift_start_iso = ""
        shift_duration_hours = None
        shift_fuel = None

        active_shift = state.get("active_shift", "none")
        if active_shift != "none":
            operator_name = db.get_state_value("active_operator") or ""
            # Fallback: if active_operator not set (shift started before PR#70),
            # look for operator in the most recent _start log entry
            if not operator_name:
                try:
                    recent_logs = db.get_last_logs(10)
                    for log in (recent_logs or []):
                        event_type = log[0] if log else ""  # index 0: event_type
                        user_name = log[2] if log else ""  # index 2: user_name
                        if event_type and event_type.endswith("_start") and user_name:
                            operator_name = user_name
                            break
                except Exception:
                    logger.warning("Failed to get operator_name from logs fallback", exc_info=True)

        if status == "ON":
            start_time_str = state.get("start_time", "")
            start_date_str = state.get("start_date", "")
            if start_time_str:
                if start_date_str:
                    shift_start_iso = f"{start_date_str}T{start_time_str}:00"
                try:
                    if start_date_str:
                        start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
                    else:
                        logger.warning(
                            f"start_date_str відсутній для активної зміни {state.get('active_shift')}! "
                            f"Використовую поточну дату."
                        )
                        start_dt = datetime.strptime(
                            f"{datetime.now(config.KYIV).strftime('%Y-%m-%d')} {start_time_str}",
                            "%Y-%m-%d %H:%M",
                        )
                    start_dt = start_dt.replace(tzinfo=config.KYIV)
                    now = datetime.now(config.KYIV)
                    if start_dt > now:
                        start_dt -= timedelta(days=1)
                    elapsed_h = (now - start_dt).total_seconds() / 3600
                    if 0 < elapsed_h < 24:
                        estimated_fuel = max(0, current_fuel - elapsed_h * fuel_rate)
                        shift_duration_hours = round(elapsed_h, 2)
                        shift_fuel = round(elapsed_h * fuel_rate, 2)
                except (ValueError, TypeError):
                    pass

        # Мотогодини — використовуємо дані активного генератора
        gen_stats = db.get_generator_stats(active_gen)
        total_hours = float(gen_stats.get("total_hours", 0))

        # Live: якщо генератор працює — додаємо час поточної зміни
        if status == "ON" and shift_duration_hours is not None and 0 < shift_duration_hours < 24:
            total_hours_live = total_hours + shift_duration_hours
        else:
            total_hours_live = total_hours

        payload = {
            "status": status,
            "generator": active_gen,
            "generator_name": gen_name,
            "current_fuel": round(current_fuel, 1),
            "estimated_fuel": round(estimated_fuel, 1),
            "fuel_rate": fuel_rate,
            "total_hours": round(total_hours_live, 1),
            "active_shift": state.get("active_shift", "none"),
            "completed_shifts": list(completed),
            "start_time": state.get("start_time", ""),
            "shift_start": shift_start_iso,
            "operator_name": operator_name,
            "shift_duration_hours": shift_duration_hours,
            "shift_fuel": shift_fuel,
            "work_start": config.WORK_START_TIME,
            "work_end": config.WORK_END_TIME,
        }
        return payload
    except Exception as e:
        logger.exception("api_status error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_schedule(request: Request):
    """GET /api/schedule?date=YYYY-MM-DD — графік відключень."""
    try:
        date_str = request.query_params.get("date")
        if not date_str:
            now = datetime.now(config.KYIV)
            date_str = now.strftime("%Y-%m-%d")

        # Валідація формату та реальності дати
        try:
            parsed = datetime.strptime(date_str, "%Y-%m-%d")
            if parsed.year < 2000 or parsed.year > 2100:
                raise ValueError("Дата поза допустимим діапазоном")
        except ValueError:
            return JSONResponse(
                content={"error": "Невірний формат або нереальна дата. Використовуйте YYYY-MM-DD"}, status_code=400
            )

        schedule = db.get_schedule(date_str)
        hours = []
        for h in range(24):
            end_h = "24:00" if h == 23 else f"{(h + 1):02d}:00"
            hours.append(
                {
                    "hour": h,
                    "label": f"{h:02d}:00 — {end_h}",
                    "off": schedule.get(h, 0) == 1,
                }
            )

        return {"date": date_str, "hours": hours}
    except Exception as e:
        logger.exception("api_schedule error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_schedule_week(request: Request):
    """GET /api/schedule/week — графік на тиждень (сьогодні + 6 днів)."""
    try:
        now = datetime.now(config.KYIV)
        days = []
        for i in range(7):
            day = now + timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")
            schedule = db.get_schedule(date_str)
            off_count = sum(1 for v in schedule.values() if v == 1)
            days.append(
                {
                    "date": date_str,
                    "weekday": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"][day.weekday()],
                    "off_hours": off_count,
                }
            )
        return {"days": days}
    except Exception as e:
        logger.exception("api_schedule_week error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_user_role(request: Request):
    """GET /api/user/role — роль поточного користувача."""
    user = _validation_mod.extract_user(request)
    try:
        user_id = int(user.get("id", 0)) if user else None
    except (TypeError, ValueError):
        user_id = None

    is_admin = _permissions_mod.is_admin(user)
    role = _permissions_mod.get_user_role(user)
    personnel = db.get_personnel_for_user(user_id) if user_id else None

    return {
        "user_id": user_id,
        "role": role,
        "is_admin": is_admin,
        "personnel": personnel,
        "has_personnel": bool(personnel),
        "first_name": user.get("first_name", "") if user else "",
    }


async def api_drivers(request: Request):
    """GET /api/drivers — список водіїв."""
    try:
        drivers = db.get_drivers()
        return {"drivers": list(drivers) if drivers else []}
    except Exception as e:
        logger.exception("api_drivers error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_generators(request: Request):
    """GET /api/generators — статистика обох генераторів."""
    try:
        active_gen = db.get_active_generator()
        state = db.get_state()
        status = state.get("status", "OFF")

        # Розраховуємо elapsed_h для live мотогодин
        live_elapsed_h = 0.0
        if status == "ON":
            try:
                start_time_str = state.get("start_time", "")
                start_date_str = state.get("start_date", "")
                if start_time_str and start_date_str:
                    start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
                    start_dt = start_dt.replace(tzinfo=config.KYIV)
                    now = datetime.now(config.KYIV)
                    if start_dt > now:
                        start_dt -= timedelta(days=1)
                    elapsed = (now - start_dt).total_seconds() / 3600
                    if 0 < elapsed < 24:
                        live_elapsed_h = elapsed
            except Exception:
                pass

        main_stats = db.get_generator_stats("main")
        emerg_stats = db.get_generator_stats("emergency")

        def _fmt_stats(stats, gen_id):
            hours = float(stats.get("total_hours", 0))
            # Додаємо elapsed тільки до АКТИВНОГО генератора
            if gen_id == active_gen and live_elapsed_h > 0:
                hours += live_elapsed_h
            return {
                "total_hours": round(hours, 1),
                "last_oil_change": round(float(stats.get("last_oil_change", 0)), 1),
                "last_spark_change": round(float(stats.get("last_spark_change", 0)), 1),
            }

        return {
            "active": active_gen,
            "main": {"name": db.get_generator_name("main"), **_fmt_stats(main_stats, "main")},
            "emergency": {"name": db.get_generator_name("emergency"), **_fmt_stats(emerg_stats, "emergency")},
        }
    except Exception as e:
        logger.exception("api_generators error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_personnel_me(request: Request):
    """GET /api/personnel/me — персонал поточного користувача."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)

    user_id = int(user.get("id", 0))
    personnel = db.get_personnel_for_user(user_id)
    all_personnel = db.get_personnel_names()

    return {
        "personnel": personnel,
        "all_names": all_personnel,
    }


async def api_schedule_toggle(request: Request):
    """POST /api/schedule/toggle — перемикання години графіка відключень."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    date_str = (body.get("date") or "").strip()
    try:
        hour = int(body.get("hour", -1))
    except (TypeError, ValueError):
        return JSONResponse(content={"error": "Невірна година"}, status_code=400)

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return JSONResponse(content={"error": "Невірний формат дати"}, status_code=400)

    if not (0 <= hour <= 23):
        return JSONResponse(content={"error": "Година повинна бути від 0 до 23"}, status_code=400)

    try:
        db.toggle_schedule(date_str, hour)
        schedule = db.get_schedule(date_str)
        new_state = bool(schedule.get(hour, 0))
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id,
            admin_name,
            "schedule_toggle",
            f"Перемикання графіка {date_str} {hour:02d}:00 → {'відключення' if new_state else 'подача'}",
            target_entity=f"schedule:{date_str}:{hour}",
            new_value={"off": new_state},
        )
        return {
            "ok": True,
            "date": date_str,
            "hour": hour,
            "off": new_state,
            "schedule": {str(h): bool(v) for h, v in schedule.items()},
        }
    except Exception as e:
        logger.exception("api_schedule_toggle error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_generator_switch(request: Request):
    """POST /api/generator/switch — перемикання активного генератора."""
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    target = (body.get("target") or "").strip()
    if target not in ("main", "emergency"):
        return JSONResponse(content={"error": "Невірний генератор (main або emergency)"}, status_code=400)

    user_id = int(user.get("id", 0))
    user_info = db.get_user(user_id)
    admin_name = user_info[1] if user_info else user.get("first_name", "Адмін")

    try:
        prev_gen = db.get_active_generator()
        success, message = db.switch_generator(target, admin_name)
        db.log_admin_action(
            user_id,
            admin_name,
            "gen_switch",
            f"Перемикання генератора: {prev_gen} → {target}",
            target_entity=f"generator:{target}",
            old_value=prev_gen,
            new_value=target,
            success=success,
        )
        if success:
            return {"ok": True, "message": message, "active": target}
        return JSONResponse(content={"error": message}, status_code=400)
    except Exception as e:
        logger.exception("api_generator_switch error")
        return JSONResponse(content={"error": str(e)}, status_code=500)
