"""
Telegram Mini App — веб-сервер.

Забезпечує:
  • роздачу статичних файлів (webapp/)
  • REST API для мініаппу (/api/*)
  • валідацію Telegram WebApp initData (HMAC-SHA256)

Запуск:
    python webapp_server.py          # порт за замовчуванням 8080
    WEBAPP_PORT=3000 python webapp_server.py
"""

import hashlib
import hmac
import io
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote

from aiohttp import web

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.cell.cell import MergedCell
    from openpyxl.utils import get_column_letter
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False
    MergedCell = None
    get_column_letter = None

# Додаємо кореневу директорію проєкту до sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import config  # noqa: E402
import database.models as db_models  # noqa: E402
import database.db_api as db  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константи
# ---------------------------------------------------------------------------
MAX_EVENTS_LIMIT = 100

# ---------------------------------------------------------------------------
# Telegram WebApp — валідація initData
# ---------------------------------------------------------------------------

def _validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Перевіряє підпис Telegram WebApp initData.

    Повертає розпарсені дані користувача або ``None`` якщо підпис
    невалідний.

    Алгоритм: https://core.telegram.org/bots/webapps#validating-data
    """
    if not init_data:
        return None

    parsed = parse_qs(init_data, keep_blank_values=True)
    received_hash = parsed.pop("hash", [None])[0]
    if not received_hash:
        return None

    # Формуємо data-check-string
    items = []
    for key in sorted(parsed):
        val = parsed[key][0]
        items.append(f"{key}={val}")
    data_check_string = "\n".join(items)

    # HMAC-SHA256
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        return None

    # Витягуємо user
    user_raw = parsed.get("user", [None])[0]
    if user_raw:
        try:
            return json.loads(unquote(user_raw))
        except (json.JSONDecodeError, TypeError):
            pass

    return {}


def _extract_user(request: web.Request) -> dict | None:
    """Витягує та валідує користувача з заголовка або query-параметра init_data."""
    # Спочатку заголовок
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    # Якщо відсутній — перевіряємо query-параметр (для прямих завантажень)
    if not init_data:
        init_data = request.query.get("init_data", "")
    if not init_data:
        return None
    bot_token = config.BOT_TOKEN or ""
    return _validate_init_data(init_data, bot_token)


# ---------------------------------------------------------------------------
# Middleware — CORS
# ---------------------------------------------------------------------------

@web.middleware
async def cors_middleware(request: web.Request, handler):
    """Додає CORS-заголовки до всіх відповідей."""
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as exc:
            resp = exc

    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
    return resp


# ---------------------------------------------------------------------------
# API — endpoints
# ---------------------------------------------------------------------------

async def api_status(request: web.Request) -> web.Response:
    """GET /api/status — поточний стан генератора."""
    try:
        state = db.get_state()
        active_gen = db.get_active_generator()
        gen_name = db.get_generator_name(active_gen)
        completed = db.get_today_completed_shifts()
        fuel_rate = db.get_fuel_consumption_rate()

        # Оцінка палива під час роботи
        current_fuel = float(state.get("current_fuel", 0))
        status = state.get("status", "OFF")
        estimated_fuel = current_fuel

        if status == "ON":
            start_time_str = state.get("start_time", "")
            start_date_str = state.get("start_date", "")
            if start_time_str:
                try:
                    if start_date_str:
                        start_dt = datetime.strptime(
                            f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M"
                        )
                    else:
                        start_dt = datetime.strptime(
                            f"{datetime.now(config.KYIV).strftime('%Y-%m-%d')} {start_time_str}",
                            "%Y-%m-%d %H:%M",
                        )
                    start_dt = start_dt.replace(tzinfo=config.KYIV)
                    now = datetime.now(config.KYIV)
                    elapsed_h = (now - start_dt).total_seconds() / 3600
                    if 0 < elapsed_h < 24:
                        estimated_fuel = max(0, current_fuel - elapsed_h * fuel_rate)
                except (ValueError, TypeError):
                    pass

        # Мотогодини — використовуємо дані активного генератора
        gen_stats = db.get_generator_stats(active_gen)
        total_hours = float(gen_stats.get("total_hours", 0))

        payload = {
            "status": status,
            "generator": active_gen,
            "generator_name": gen_name,
            "current_fuel": round(current_fuel, 1),
            "estimated_fuel": round(estimated_fuel, 1),
            "fuel_rate": fuel_rate,
            "total_hours": round(total_hours, 1),
            "active_shift": state.get("active_shift", "none"),
            "completed_shifts": list(completed),
            "start_time": state.get("start_time", ""),
            "work_start": config.WORK_START_TIME,
            "work_end": config.WORK_END_TIME,
        }
        return web.json_response(payload)
    except Exception as e:
        logger.exception("api_status error")
        return web.json_response({"error": str(e)}, status=500)


async def api_schedule(request: web.Request) -> web.Response:
    """GET /api/schedule?date=YYYY-MM-DD — графік відключень."""
    try:
        date_str = request.query.get("date")
        if not date_str:
            now = datetime.now(config.KYIV)
            date_str = now.strftime("%Y-%m-%d")

        # Валідація формату дати
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return web.json_response({"error": "Невірний формат дати. Використовуйте YYYY-MM-DD"}, status=400)

        schedule = db.get_schedule(date_str)
        hours = []
        for h in range(24):
            end_h = "24:00" if h == 23 else f"{(h + 1):02d}:00"
            hours.append({
                "hour": h,
                "label": f"{h:02d}:00 — {end_h}",
                "off": schedule.get(h, 0) == 1,
            })

        return web.json_response({"date": date_str, "hours": hours})
    except Exception as e:
        logger.exception("api_schedule error")
        return web.json_response({"error": str(e)}, status=500)


async def api_events(request: web.Request) -> web.Response:
    """GET /api/events?limit=20 — останні події."""
    try:
        limit = min(int(request.query.get("limit", "20")), MAX_EVENTS_LIMIT)
    except (ValueError, TypeError):
        limit = 20

    try:
        rows = db.get_last_logs(limit)
        events = []
        for row in rows:
            events.append({
                "event_type": row[0] if len(row) > 0 else "",
                "timestamp": row[1] if len(row) > 1 else "",
                "actor": row[2] if len(row) > 2 else "",
                "value": row[3] if len(row) > 3 else "",
                "driver": row[4] if len(row) > 4 else "",
                "receipt": row[5] if len(row) > 5 else "",
            })
        return web.json_response({"events": events, "count": len(events)})
    except Exception as e:
        logger.exception("api_events error")
        return web.json_response({"error": str(e)}, status=500)


async def api_maintenance(request: web.Request) -> web.Response:
    """GET /api/maintenance — стан технічного обслуговування."""
    try:
        active_gen = db.get_active_generator()
        stats = db.get_maintenance_stats(active_gen)
        history = db.get_maintenance_history(active_gen, 10)

        history_list = []
        for row in history:
            history_list.append({
                "id": row[0] if len(row) > 0 else None,
                "date": row[1] if len(row) > 1 else "",
                "type": row[2] if len(row) > 2 else "",
                "hours": row[3] if len(row) > 3 else 0,
                "admin": row[4] if len(row) > 4 else "",
            })

        # Додаємо інтервали ТО з конфігурації для прогрес-барів
        stats["oil_interval"] = config.OIL_CHANGE_INTERVAL
        stats["spark_interval"] = config.SPARK_CHANGE_INTERVAL
        stats["maintenance_interval"] = config.MAINTENANCE_INTERVAL

        return web.json_response({
            "generator": active_gen,
            "stats": stats,
            "history": history_list,
        })
    except Exception as e:
        logger.exception("api_maintenance error")
        return web.json_response({"error": str(e)}, status=500)


async def api_schedule_week(request: web.Request) -> web.Response:
    """GET /api/schedule/week — графік на тиждень (сьогодні + 6 днів)."""
    try:
        now = datetime.now(config.KYIV)
        days = []
        for i in range(7):
            day = now + timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")
            schedule = db.get_schedule(date_str)
            off_count = sum(1 for v in schedule.values() if v == 1)
            days.append({
                "date": date_str,
                "weekday": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"][day.weekday()],
                "off_hours": off_count,
            })
        return web.json_response({"days": days})
    except Exception as e:
        logger.exception("api_schedule_week error")
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# Нові API-ендпоінти для повного функціоналу Mini App
# ---------------------------------------------------------------------------

def _is_admin(user: dict | None) -> bool:
    """Перевіряє чи є користувач адміністратором."""
    if not user:
        return False
    user_id = user.get("id")
    return bool(user_id and int(user_id) in config.ADMIN_IDS)


def _within_work_window(now_t, start_t, end_t) -> bool:
    """True якщо now_t знаходиться в [start_t, end_t)."""
    if start_t <= end_t:
        return start_t <= now_t < end_t
    return now_t >= start_t or now_t < end_t


async def api_user_role(request: web.Request) -> web.Response:
    """GET /api/user/role — роль поточного користувача."""
    user = _extract_user(request)
    user_id = int(user.get("id", 0)) if user else None

    is_admin = bool(user_id and user_id in config.ADMIN_IDS)
    personnel = db.get_personnel_for_user(user_id) if user_id else None

    return web.json_response({
        "user_id": user_id,
        "is_admin": is_admin,
        "personnel": personnel,
        "has_personnel": bool(personnel),
        "first_name": user.get("first_name", "") if user else "",
    })


async def api_drivers(request: web.Request) -> web.Response:
    """GET /api/drivers — список водіїв."""
    try:
        drivers = db.get_drivers()
        return web.json_response({"drivers": list(drivers) if drivers else []})
    except Exception as e:
        logger.exception("api_drivers error")
        return web.json_response({"error": str(e)}, status=500)


async def api_generators(request: web.Request) -> web.Response:
    """GET /api/generators — статистика обох генераторів."""
    try:
        active_gen = db.get_active_generator()
        main_stats = db.get_generator_stats("main")
        emerg_stats = db.get_generator_stats("emergency")

        def _fmt_stats(stats):
            return {
                "total_hours": round(float(stats.get("total_hours", 0)), 1),
                "last_oil_change": round(float(stats.get("last_oil_change", 0)), 1),
                "last_spark_change": round(float(stats.get("last_spark_change", 0)), 1),
            }

        return web.json_response({
            "active": active_gen,
            "main": {"name": db.get_generator_name("main"), **_fmt_stats(main_stats)},
            "emergency": {"name": db.get_generator_name("emergency"), **_fmt_stats(emerg_stats)},
        })
    except Exception as e:
        logger.exception("api_generators error")
        return web.json_response({"error": str(e)}, status=500)


async def api_personnel_me(request: web.Request) -> web.Response:
    """GET /api/personnel/me — персонал поточного користувача."""
    user = _extract_user(request)
    if not user:
        return web.json_response({"error": "Не авторизовано"}, status=401)

    user_id = int(user.get("id", 0))
    personnel = db.get_personnel_for_user(user_id)
    all_personnel = db.get_personnel_names()

    return web.json_response({
        "personnel": personnel,
        "all_names": all_personnel,
    })


async def api_action_start(request: web.Request) -> web.Response:
    """POST /api/action/start — старт зміни генератора."""
    user = _extract_user(request)
    if not user:
        return web.json_response({"error": "Не авторизовано"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    shift_code = (body.get("shift") or "").strip()
    if shift_code not in ("m", "d", "e", "x"):
        return web.json_response({"error": "Невірний код зміни"}, status=400)

    user_id = int(user.get("id", 0))
    personnel = db.get_personnel_for_user(user_id)
    if not personnel:
        return web.json_response(
            {"error": "Нема прив'язки до персоналу. Зверніться до адміністратора."},
            status=400,
        )

    now = datetime.now(config.KYIV)

    # Перевірка робочого часу
    try:
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        end_t = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        if not _within_work_window(now.time(), start_t, end_t):
            return web.json_response(
                {"error": f"Заборонено поза робочим часом ({config.WORK_START_TIME}–{config.WORK_END_TIME})"},
                status=400,
            )
    except Exception:
        pass

    event_type = shift_code + "_start"
    res = db.try_start_shift(event_type, personnel, now)
    if not res.get("ok"):
        reason = res.get("reason", "error")
        if reason == "already_on":
            active = res.get("active_shift", "none")
            return web.json_response({"error": f"Генератор вже працює (активна зміна: {active})"}, status=400)
        return web.json_response({"error": "Помилка старту зміни"}, status=400)

    return web.json_response({
        "ok": True,
        "message": f"Зміна запущена о {now.strftime('%H:%M')}",
        "shift": shift_code,
        "time": now.strftime("%H:%M"),
    })


async def api_action_stop(request: web.Request) -> web.Response:
    """POST /api/action/stop — зупинка зміни генератора."""
    user = _extract_user(request)
    if not user:
        return web.json_response({"error": "Не авторизовано"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    shift_code = (body.get("shift") or "").strip()
    if shift_code not in ("m", "d", "e", "x"):
        return web.json_response({"error": "Невірний код зміни"}, status=400)

    user_id = int(user.get("id", 0))
    personnel = db.get_personnel_for_user(user_id)
    if not personnel:
        return web.json_response(
            {"error": "Нема прив'язки до персоналу. Зверніться до адміністратора."},
            status=400,
        )

    now = datetime.now(config.KYIV)
    event_type = shift_code + "_end"
    res = db.try_stop_shift(event_type, personnel, now)
    if not res.get("ok"):
        reason = res.get("reason", "error")
        if reason == "already_off":
            return web.json_response({"error": "Генератор вже вимкнено"}, status=400)
        if reason == "wrong_shift":
            active = res.get("active_shift", "none")
            return web.json_response({"error": f"Зараз активна інша зміна: {active}"}, status=400)
        return web.json_response({"error": "Помилка зупинки зміни"}, status=400)

    duration_hours = res.get("duration_hours", 0.0)
    fuel_consumed = res.get("fuel_consumed", 0.0)
    h = int(duration_hours)
    m = int((duration_hours - h) * 60)

    return web.json_response({
        "ok": True,
        "message": f"Зміна закрита о {now.strftime('%H:%M')}",
        "shift": shift_code,
        "duration": f"{h:02d}:{m:02d}",
        "fuel_consumed": round(fuel_consumed, 1),
    })


async def api_action_refill(request: web.Request) -> web.Response:
    """POST /api/action/refill — прийом палива."""
    user = _extract_user(request)
    if not user:
        return web.json_response({"error": "Не авторизовано"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    driver = (body.get("driver") or "").strip()
    receipt = (body.get("receipt") or "").strip()
    try:
        liters = float(body.get("liters", 0))
    except (TypeError, ValueError):
        return web.json_response({"error": "Невірна кількість літрів"}, status=400)

    if not driver:
        return web.json_response({"error": "Оберіть водія"}, status=400)
    if not receipt or len(receipt) > 50:
        return web.json_response({"error": "Введіть коректний номер чека"}, status=400)
    if liters <= 0 or liters > 500:
        return web.json_response({"error": "Кількість літрів має бути від 1 до 500"}, status=400)

    user_id = int(user.get("id", 0))
    personnel = db.get_personnel_for_user(user_id)
    if not personnel:
        return web.json_response(
            {"error": "Нема прив'язки до персоналу. Зверніться до адміністратора."},
            status=400,
        )

    # Перевірка робочого часу
    now = datetime.now(config.KYIV)
    try:
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        end_t = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        if not _within_work_window(now.time(), start_t, end_t):
            return web.json_response(
                {"error": f"Прийом палива заборонено поза робочим часом ({config.WORK_START_TIME}–{config.WORK_END_TIME})"},
                status=400,
            )
    except Exception:
        pass

    try:
        from database.models import get_connection, begin_transaction
        conn = get_connection()
        begin_transaction(conn)
        db.add_log("refill", personnel, str(liters), driver, receipt=receipt, conn=conn)
        db.update_fuel(liters, conn=conn)
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("api_action_refill error")
        return web.json_response({"error": str(e)}, status=500)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return web.json_response({
        "ok": True,
        "message": f"Прийнято {liters:.1f} л палива (Водій: {driver}, Чек: {receipt})",
        "liters": liters,
        "driver": driver,
        "receipt": receipt,
    })


async def api_schedule_toggle(request: web.Request) -> web.Response:
    """POST /api/schedule/toggle — перемикання години графіка відключень."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    date_str = (body.get("date") or "").strip()
    try:
        hour = int(body.get("hour", -1))
    except (TypeError, ValueError):
        return web.json_response({"error": "Невірна година"}, status=400)

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return web.json_response({"error": "Невірний формат дати"}, status=400)

    if not (0 <= hour <= 23):
        return web.json_response({"error": "Година повинна бути від 0 до 23"}, status=400)

    try:
        db.toggle_schedule(date_str, hour)
        schedule = db.get_schedule(date_str)
        return web.json_response({
            "ok": True,
            "date": date_str,
            "hour": hour,
            "off": bool(schedule.get(hour, 0)),
            "schedule": {str(h): bool(v) for h, v in schedule.items()},
        })
    except Exception as e:
        logger.exception("api_schedule_toggle error")
        return web.json_response({"error": str(e)}, status=500)


async def api_generator_switch(request: web.Request) -> web.Response:
    """POST /api/generator/switch — перемикання активного генератора."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    target = (body.get("target") or "").strip()
    if target not in ("main", "emergency"):
        return web.json_response({"error": "Невірний генератор (main або emergency)"}, status=400)

    user_id = int(user.get("id", 0))
    user_info = db.get_user(user_id)
    admin_name = user_info[1] if user_info else user.get("first_name", "Адмін")

    try:
        success, message = db.switch_generator(target, admin_name)
        if success:
            return web.json_response({"ok": True, "message": message, "active": target})
        return web.json_response({"error": message}, status=400)
    except Exception as e:
        logger.exception("api_generator_switch error")
        return web.json_response({"error": str(e)}, status=500)


async def api_maintenance_perform(request: web.Request) -> web.Response:
    """POST /api/maintenance/perform — виконання технічного обслуговування."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    action = (body.get("action") or "").strip()
    generator_id = (body.get("generator") or "main").strip()

    if action not in ("oil", "spark", "maintenance"):
        return web.json_response({"error": "Невірний тип ТО (oil, spark, maintenance)"}, status=400)
    if generator_id not in ("main", "emergency"):
        return web.json_response({"error": "Невірний генератор"}, status=400)

    user_id = int(user.get("id", 0))
    user_info = db.get_user(user_id)
    actor = user_info[1] if user_info else user.get("first_name", "Адмін")

    try:
        db.record_maintenance(action, actor, generator_id)
        action_names = {"oil": "Заміна мастила", "spark": "Заміна свічок", "maintenance": "Планове ТО"}
        return web.json_response({
            "ok": True,
            "message": f"{action_names.get(action, action)} виконано",
        })
    except Exception as e:
        logger.exception("api_maintenance_perform error")
        return web.json_response({"error": str(e)}, status=500)


async def api_maintenance_set_hours(request: web.Request) -> web.Response:
    """POST /api/maintenance/set-hours — встановлення мотогодин генератора."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    generator_id = (body.get("generator") or "main").strip()
    try:
        hours = float(body.get("hours", -1))
    except (TypeError, ValueError):
        return web.json_response({"error": "Невірне значення мотогодин"}, status=400)

    if generator_id not in ("main", "emergency"):
        return web.json_response({"error": "Невірний генератор"}, status=400)
    if hours < 0 or hours > 100000:
        return web.json_response({"error": "Значення мотогодин поза допустимим діапазоном (0–100000)"}, status=400)

    try:
        db.set_total_hours(hours, generator_id)
        return web.json_response({
            "ok": True,
            "message": f"Мотогодини встановлено: {hours:.1f} год",
            "hours": hours,
        })
    except Exception as e:
        logger.exception("api_maintenance_set_hours error")
        return web.json_response({"error": str(e)}, status=500)


async def api_fuel_set(request: web.Request) -> web.Response:
    """POST /api/fuel/set — встановлення поточного рівня палива (адмін)."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    try:
        fuel = float(body.get("fuel", -1))
    except (TypeError, ValueError):
        return web.json_response({"error": "Невірне значення палива"}, status=400)

    if fuel < 0 or fuel > 10000:
        return web.json_response({"error": "Значення палива поза допустимим діапазоном"}, status=400)

    try:
        db.set_state("current_fuel", str(fuel))
        user_id = int(user.get("id", 0))
        user_info = db.get_user(user_id)
        actor = user_info[1] if user_info else user.get("first_name", "Адмін")
        db.add_log("corr_fuel_set", actor, str(fuel))
        return web.json_response({"ok": True, "message": f"Паливо встановлено: {fuel:.1f} л"})
    except Exception as e:
        logger.exception("api_fuel_set error")
        return web.json_response({"error": str(e)}, status=500)


async def api_report_excel(request: web.Request) -> web.Response:
    """GET /api/report/excel — завантаження Excel-звіту."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    if not EXCEL_AVAILABLE:
        return web.json_response({"error": "Модуль openpyxl не встановлено"}, status=500)

    try:
        period_days = int(request.query.get("days", "30"))
        if period_days < 1:
            period_days = 30
        if period_days > 365:
            period_days = 365
    except (ValueError, TypeError):
        period_days = 30

    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "Журнал подій"

        header_fill = PatternFill(start_color="2481CC", end_color="2481CC", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")

        # Заголовок звіту
        now = datetime.now(config.KYIV)
        ws["A1"] = f"Звіт генератора — {now.strftime('%d.%m.%Y %H:%M')}"
        ws["A1"].font = Font(bold=True, size=14)
        ws.merge_cells("A1:F1")

        # Загальний стан
        state = db.get_state()
        active_gen = db.get_active_generator()
        gen_name = db.get_generator_name(active_gen)

        ws["A3"] = "Активний генератор:"
        ws["B3"] = gen_name
        ws["A4"] = "Статус:"
        ws["B4"] = state.get("status", "OFF")
        ws["A5"] = "Залишок палива:"
        ws["B5"] = f"{float(state.get('current_fuel', 0)):.1f} л"

        # Заголовки таблиці
        col_headers = ["Дата/Час", "Подія", "Користувач", "Значення", "Водій", "Чек"]
        for col_idx, header in enumerate(col_headers, start=1):
            cell = ws.cell(row=7, column=col_idx)
            cell.value = header
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        event_names = {
            "m_start": "🌅 Зміна 1 (початок)",
            "m_end": "🌅 Зміна 1 (кінець)",
            "d_start": "☀️ Зміна 2 (початок)",
            "d_end": "☀️ Зміна 2 (кінець)",
            "e_start": "🌙 Зміна 3 (початок)",
            "e_end": "🌙 Зміна 3 (кінець)",
            "x_start": "⚡ Екстра (початок)",
            "x_end": "⚡ Екстра (кінець)",
            "refill": "⛽ Прийом палива",
            "corr_fuel_set": "🔧 Корекція палива",
            "sync": "🔄 Синхронізація",
            "mnt_oil": "🛢 Заміна мастила",
            "mnt_spark": "🕯 Заміна свічок",
            "mnt_maintenance": "🔧 Планове ТО",
            "mnt_set_hours": "⏱ Корекція мотогодин",
            "auto_stop": "⏰ Авто-зупинка",
        }

        end_date = now.strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=period_days)).strftime("%Y-%m-%d")
        logs = db.get_logs_for_period(start_date, end_date)

        row = 8
        for log in logs:
            event_type, timestamp, user_name, value, driver_name, receipt_number, *_ = log
            ws.cell(row=row, column=1).value = timestamp
            ws.cell(row=row, column=2).value = event_names.get(event_type, event_type)
            ws.cell(row=row, column=3).value = user_name or "—"
            ws.cell(row=row, column=4).value = value or "—"
            ws.cell(row=row, column=5).value = driver_name or "—"
            ws.cell(row=row, column=6).value = receipt_number or "—"
            row += 1

        # Аркуш ТО
        ws2 = wb.create_sheet("ТО")
        ws2["A1"] = "Технічне обслуговування"
        ws2["A1"].font = Font(bold=True, size=14)
        ws2.merge_cells("A1:E1")

        for gen_id in ("main", "emergency"):
            stats = db.get_maintenance_stats(gen_id)
            gen_label = db.get_generator_name(gen_id)
            history = db.get_maintenance_history(gen_id, 50)

            row2 = ws2.max_row + 2
            ws2.cell(row=row2, column=1).value = gen_label
            ws2.cell(row=row2, column=1).font = Font(bold=True, size=12)
            row2 += 1

            ws2.cell(row=row2, column=1).value = "Мотогодини:"
            ws2.cell(row=row2, column=2).value = f"{float(stats.get('total_hours', 0)):.1f} год"
            row2 += 1

            col_h2 = ["Дата", "Тип ТО", "Мотогодини", "Виконав"]
            for ci, h in enumerate(col_h2, start=1):
                c = ws2.cell(row=row2, column=ci)
                c.value = h
                c.fill = header_fill
                c.font = header_font
            row2 += 1

            for rec in history:
                rec_id, date_str, action, hours, admin, *_ = rec
                ws2.cell(row=row2, column=1).value = date_str
                ws2.cell(row=row2, column=2).value = {"oil": "Мастило", "spark": "Свічки", "maintenance": "Планове ТО"}.get(action, action)
                ws2.cell(row=row2, column=3).value = f"{float(hours):.1f}"
                ws2.cell(row=row2, column=4).value = admin or "—"
                row2 += 1

        # Автоширина (безпечно з MergedCell)
        for ws_sheet in [ws, ws2]:
            for col_idx in range(1, ws_sheet.max_column + 1):
                max_len = 0
                col_letter = get_column_letter(col_idx)
                for row_idx in range(1, ws_sheet.max_row + 1):
                    cell = ws_sheet.cell(row=row_idx, column=col_idx)
                    if MergedCell and isinstance(cell, MergedCell):
                        continue
                    try:
                        cell_len = len(str(cell.value or ""))
                        if cell_len > max_len:
                            max_len = cell_len
                    except Exception:
                        pass
                ws_sheet.column_dimensions[col_letter].width = min(max_len + 2, 50)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f"generator_report_{now.strftime('%Y%m%d_%H%M')}.xlsx"
        return web.Response(
            body=buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("api_report_excel error")
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# Статичні файли та додаток
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    """Створює aiohttp-додаток з API та статичними файлами."""
    app = web.Application(middlewares=[cors_middleware])

    # API маршрути (читання)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/schedule", api_schedule)
    app.router.add_get("/api/schedule/week", api_schedule_week)
    app.router.add_get("/api/events", api_events)
    app.router.add_get("/api/maintenance", api_maintenance)
    # Нові GET-ендпоінти
    app.router.add_get("/api/user/role", api_user_role)
    app.router.add_get("/api/drivers", api_drivers)
    app.router.add_get("/api/generators", api_generators)
    app.router.add_get("/api/personnel/me", api_personnel_me)
    app.router.add_get("/api/report/excel", api_report_excel)
    # POST-ендпоінти для дій
    app.router.add_post("/api/action/start", api_action_start)
    app.router.add_post("/api/action/stop", api_action_stop)
    app.router.add_post("/api/action/refill", api_action_refill)
    app.router.add_post("/api/schedule/toggle", api_schedule_toggle)
    app.router.add_post("/api/generator/switch", api_generator_switch)
    app.router.add_post("/api/maintenance/perform", api_maintenance_perform)
    app.router.add_post("/api/maintenance/set-hours", api_maintenance_set_hours)
    app.router.add_post("/api/fuel/set", api_fuel_set)

    # Статичні файли (CSS, JS)
    webapp_dir = _PROJECT_ROOT / "webapp"
    if webapp_dir.is_dir():
        app.router.add_static("/css/", webapp_dir / "css", name="css")
        app.router.add_static("/js/", webapp_dir / "js", name="js")

        # index.html — кореневий маршрут
        async def index_handler(request: web.Request) -> web.FileResponse:
            return web.FileResponse(webapp_dir / "index.html")

        app.router.add_get("/", index_handler)

    return app


def main():
    """Точка входу — запуск веб-сервера."""
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Ініціалізація БД
    logger.info("🔧 Ініціалізація бази даних...")
    db_models.init_db()

    port = int(os.getenv("WEBAPP_PORT", "8080"))
    host = os.getenv("WEBAPP_HOST", "0.0.0.0")

    app = create_app()

    logger.info(f"🌐 Mini App сервер запускається на http://{host}:{port}")
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
