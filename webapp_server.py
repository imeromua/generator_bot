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
from contextlib import contextmanager
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
MAX_NAME_LENGTH = 100

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
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
        return resp

    try:
        resp = await handler(request)
    except web.HTTPException as exc:
        resp = exc

    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
    return resp


# ---------------------------------------------------------------------------
# Rate limiting (in-memory, per-IP, 100 req/min)
# ---------------------------------------------------------------------------

import time as _time
from collections import defaultdict

_rate_limit_counts: dict = defaultdict(list)
_RATE_LIMIT_MAX = 100
_RATE_LIMIT_WINDOW = 60  # seconds


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    """Simple in-memory rate limiter: 100 requests per minute per IP."""
    if request.method == "OPTIONS":
        return await handler(request)

    ip = request.remote or "unknown"
    now = _time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW

    # Remove old entries
    _rate_limit_counts[ip] = [t for t in _rate_limit_counts[ip] if t > window_start]

    if len(_rate_limit_counts[ip]) >= _RATE_LIMIT_MAX:
        logger.warning(f"⚠️ Rate limit exceeded for IP {ip}")
        return web.json_response(
            {"error": "Забагато запитів. Спробуйте пізніше."},
            status=429,
        )

    _rate_limit_counts[ip].append(now)
    return await handler(request)


# ---------------------------------------------------------------------------
# Утиліти для роботи з БД
# ---------------------------------------------------------------------------

@contextmanager
def atomic_transaction():
    """Context manager для безпечної роботи з транзакцією БД.

    Відкриває з'єднання, починає транзакцію, при успіху виконує commit,
    при помилці — rollback. З'єднання закривається у будь-якому випадку.
    """
    conn = db_models.get_connection()
    try:
        db_models.begin_transaction(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_admin_info(user: dict) -> tuple[int, str]:
    """Extract (user_id, admin_name) from validated user dict."""
    try:
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        user_id = 0
    user_info = db.get_user(user_id) if user_id else None
    admin_name = user_info[1] if user_info else user.get("first_name", "Адмін")
    return user_id, admin_name


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

        # Валідація формату та реальності дати
        try:
            parsed = datetime.strptime(date_str, "%Y-%m-%d")
            if parsed.year < 2000 or parsed.year > 2100:
                raise ValueError("Дата поза допустимим діапазоном")
        except ValueError:
            return web.json_response(
                {"error": "Невірний формат або нереальна дата. Використовуйте YYYY-MM-DD"},
                status=400,
            )

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
    try:
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        return False
    return bool(user_id and user_id in config.ADMIN_IDS)


def _within_work_window(now_t, start_t, end_t) -> bool:
    """True якщо now_t знаходиться в [start_t, end_t)."""
    if start_t <= end_t:
        return start_t <= now_t < end_t
    return now_t >= start_t or now_t < end_t


async def api_user_role(request: web.Request) -> web.Response:
    """GET /api/user/role — роль поточного користувача."""
    user = _extract_user(request)
    try:
        user_id = int(user.get("id", 0)) if user else None
    except (TypeError, ValueError):
        user_id = None

    is_admin = _is_admin(user)
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
        with atomic_transaction() as conn:
            db.add_log("refill", personnel, str(liters), driver, receipt=receipt, conn=conn)
            db.update_fuel(liters, conn=conn)
    except Exception as e:
        logger.exception("api_action_refill error")
        return web.json_response({"error": str(e)}, status=500)

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
        new_state = bool(schedule.get(hour, 0))
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name, "schedule_toggle",
            f"Перемикання графіка {date_str} {hour:02d}:00 → {'відключення' if new_state else 'подача'}",
            target_entity=f"schedule:{date_str}:{hour}",
            new_value={"off": new_state},
        )
        return web.json_response({
            "ok": True,
            "date": date_str,
            "hour": hour,
            "off": new_state,
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
        prev_gen = db.get_active_generator()
        success, message = db.switch_generator(target, admin_name)
        db.log_admin_action(
            user_id, admin_name, "gen_switch",
            f"Перемикання генератора: {prev_gen} → {target}",
            target_entity=f"generator:{target}",
            old_value=prev_gen,
            new_value=target,
            success=success,
        )
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
        db.log_admin_action(
            user_id, actor, "maintenance_perform",
            f"{action_names.get(action, action)} на генераторі {generator_id}",
            target_entity=f"generator:{generator_id}",
            new_value={"action": action, "generator": generator_id},
        )
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
        old_stats = db.get_generator_stats(generator_id)
        old_hours = float(old_stats.get("total_hours", 0))
        db.set_total_hours(hours, generator_id)
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name, "mnt_set_hours",
            f"Корекція мотогодин генератора {generator_id}: {old_hours:.1f} → {hours:.1f} год",
            target_entity=f"generator:{generator_id}",
            old_value=old_hours,
            new_value=hours,
        )
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
        old_state = db.get_state()
        old_fuel = float(old_state.get("current_fuel", 0))
        db.set_state("current_fuel", str(fuel))
        user_id = int(user.get("id", 0))
        user_info = db.get_user(user_id)
        actor = user_info[1] if user_info else user.get("first_name", "Адмін")
        db.add_log("corr_fuel_set", actor, str(fuel))
        db.log_admin_action(
            user_id, actor, "fuel_set",
            f"Корекція палива: {old_fuel:.1f} → {fuel:.1f} л",
            target_entity="fuel",
            old_value=old_fuel,
            new_value=fuel,
        )
        return web.json_response({"ok": True, "message": f"Паливо встановлено: {fuel:.1f} л"})
    except Exception as e:
        logger.exception("api_fuel_set error")
        return web.json_response({"error": str(e)}, status=500)


def _build_daily_report_wb(generator_id: str, period_days: int, now: datetime) -> "Workbook":
    """Будує Excel-книгу з детальним щоденним звітом для одного генератора.

    Стовпці: Дата | Зміна 1 (поч/кін) | Зміна 2 | Зміна 3 | Екстра |
             Залишок ранок | Витрата | Залишок вечір | Мотогодини |
             Заправка (л) | Хто привіз | № чека
    """
    if not EXCEL_AVAILABLE:
        raise RuntimeError("openpyxl не встановлено")

    from collections import defaultdict

    wb = Workbook()

    gen_name = db.get_generator_name(generator_id)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=period_days)).strftime("%Y-%m-%d")

    # --- Кольори ---
    BLUE_FILL   = PatternFill(start_color="2481CC", end_color="2481CC", fill_type="solid")
    LBLUE_FILL  = PatternFill(start_color="D6E8FA", end_color="D6E8FA", fill_type="solid")
    GREEN_FILL  = PatternFill(start_color="27AE60", end_color="27AE60", fill_type="solid")
    ORANGE_FILL = PatternFill(start_color="F39C12", end_color="F39C12", fill_type="solid")
    WHITE_FONT  = Font(bold=True, color="FFFFFF", size=11)
    BOLD_FONT   = Font(bold=True, size=11)
    BORDER_SIDE = None
    try:
        from openpyxl.styles import Border, Side
        thin = Side(style="thin", color="AAAAAA")
        BORDER_SIDE = Border(left=thin, right=thin, top=thin, bottom=thin)
    except Exception:
        pass

    def _style_header(cell, fill=BLUE_FILL):
        cell.font = WHITE_FONT
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if BORDER_SIDE:
            cell.border = BORDER_SIDE

    def _style_data(cell, bold=False, align="center"):
        cell.alignment = Alignment(horizontal=align, vertical="center")
        if bold:
            cell.font = Font(bold=True)
        if BORDER_SIDE:
            cell.border = BORDER_SIDE

    # ---- Аркуш «Щоденний звіт» ----
    ws = wb.active
    ws.title = "Щоденний звіт"

    # Шапка
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 18
    ws.row_dimensions[3].height = 18

    header_text = f"Звіт генератора «{gen_name}» за {period_days} днів | Сформовано: {now.strftime('%d.%m.%Y %H:%M')}"
    ws["A1"] = header_text
    ws["A1"].font = Font(bold=True, size=13, color="1A1A2E")
    ws.merge_cells("A1:M1")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws["A1"].fill = PatternFill(start_color="EAF2FB", end_color="EAF2FB", fill_type="solid")

    # Рядки заголовків стовпців
    col_headers_r2 = [
        "Дата",
        "Зміна 1\nпочаток", "Зміна 1\nкінець",
        "Зміна 2\nпочаток", "Зміна 2\nкінець",
        "Зміна 3\nпочаток", "Зміна 3\nкінець",
        "Залишок\nранок, л", "Витрата\nза день, л", "Залишок\nвечір, л",
        "Мотогодини\n(накопичено)", "Заправка\n(прихід), л",
        "Хто привіз / № чека",
    ]
    for ci, h in enumerate(col_headers_r2, start=1):
        c = ws.cell(row=2, column=ci, value=h)
        if ci == 1:
            _style_header(c, BLUE_FILL)
        elif ci in (2, 3):
            _style_header(c, PatternFill(start_color="1A7A44", end_color="1A7A44", fill_type="solid"))
        elif ci in (4, 5):
            _style_header(c, PatternFill(start_color="D4AC0D", end_color="D4AC0D", fill_type="solid"))
        elif ci in (6, 7):
            _style_header(c, PatternFill(start_color="1565C0", end_color="1565C0", fill_type="solid"))
        elif ci in (8, 9, 10):
            _style_header(c, PatternFill(start_color="6C3483", end_color="6C3483", fill_type="solid"))
        elif ci == 11:
            _style_header(c, PatternFill(start_color="2E86C1", end_color="2E86C1", fill_type="solid"))
        elif ci in (12, 13):
            _style_header(c, PatternFill(start_color="117A65", end_color="117A65", fill_type="solid"))
        ws.row_dimensions[2].height = 40

    # Ширини стовпців
    col_widths = [12, 11, 11, 11, 11, 11, 11, 13, 13, 13, 15, 13, 30]
    for ci, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    # Отримуємо всі логи за період для цього генератора
    logs = db.get_logs_for_period(start_date, end_date, generator_id)

    # Агрегуємо по датах
    days_data = defaultdict(lambda: {
        "shifts": {"m": {}, "d": {}, "e": {}, "x": {}},
        "refills": [],
        "morning_fuel": None,
        "evening_fuel": None,
        "hours_start": None,
        "hours_end": None,
    })

    for row_data in logs:
        event_type, ts_str, user_name, value, driver_name, receipt_number, *_ = row_data
        if not ts_str:
            continue
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        date_str = ts.strftime("%Y-%m-%d")
        day = days_data[date_str]

        if event_type.endswith("_start"):
            shift = event_type.split("_")[0]
            if shift in day["shifts"]:
                day["shifts"][shift]["start"] = ts.strftime("%H:%M")
        elif event_type.endswith("_end"):
            shift = event_type.split("_")[0]
            if shift in day["shifts"]:
                day["shifts"][shift]["end"] = ts.strftime("%H:%M")
        elif event_type == "refill":
            try:
                liters = float(value or 0)
            except Exception:
                liters = 0.0
            day["refills"].append((liters, (driver_name or "").strip(), (receipt_number or "").strip()))
        elif event_type == "corr_fuel_set":
            # Використовуємо останню корекцію дня як залишок
            try:
                day["evening_fuel"] = float(value or 0)
            except Exception:
                pass

    # Рядок початку — отримуємо поточний стан
    state = db.get_state()
    current_fuel = float(state.get("current_fuel", 0))

    # Генеруємо рядки за відсортованими датами
    data_row = 3
    prev_fuel = None
    fuel_rate = db.get_fuel_consumption_rate()

    for date_str in sorted(days_data.keys()):
        day = days_data[date_str]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            date_fmt = dt.strftime("%d.%m.%Y")
        except Exception:
            date_fmt = date_str

        # Розраховуємо витрату
        total_shift_mins = 0
        for shift_data in day["shifts"].values():
            s_str = shift_data.get("start")
            e_str = shift_data.get("end")
            if s_str and e_str:
                try:
                    s_t = datetime.strptime(s_str, "%H:%M")
                    e_t = datetime.strptime(e_str, "%H:%M")
                    diff = (e_t - s_t).total_seconds() / 60
                    if diff < 0:
                        diff += 24 * 60
                    total_shift_mins += diff
                except Exception:
                    pass

        total_hours = round(total_shift_mins / 60, 2)
        consumption = round(total_hours * fuel_rate, 1) if total_hours > 0 else 0.0
        refill_total = round(sum(r[0] for r in day["refills"]), 1) if day["refills"] else 0.0

        morning_fuel = day.get("morning_fuel") or prev_fuel
        if morning_fuel is not None:
            evening_fuel = round(float(morning_fuel) + refill_total - consumption, 1)
        else:
            morning_fuel = ""
            evening_fuel = ""

        prev_fuel = evening_fuel if isinstance(evening_fuel, float) else None

        drivers_str = ", ".join(
            f"{drv} (чек {rec})" if rec else drv
            for _, drv, rec in day["refills"] if drv
        ) or "—"

        row_vals = [
            date_fmt,
            day["shifts"]["m"].get("start", ""),
            day["shifts"]["m"].get("end", ""),
            day["shifts"]["d"].get("start", ""),
            day["shifts"]["d"].get("end", ""),
            day["shifts"]["e"].get("start", ""),
            day["shifts"]["e"].get("end", ""),
            morning_fuel if morning_fuel != "" else "—",
            consumption if consumption > 0 else "—",
            evening_fuel if evening_fuel != "" else "—",
            total_hours if total_hours > 0 else "—",
            refill_total if refill_total > 0 else "—",
            drivers_str,
        ]

        for ci, val in enumerate(row_vals, start=1):
            c = ws.cell(row=data_row, column=ci, value=val)
            bold = ci == 1
            align = "left" if ci == 13 else "center"
            _style_data(c, bold=bold, align=align)
            # Підсвітлення критичних залишків
            if ci == 10 and isinstance(val, float):
                if val < 15:
                    c.fill = PatternFill(start_color="FADBD8", end_color="FADBD8", fill_type="solid")
                elif val < 40:
                    c.fill = PatternFill(start_color="FDEBD0", end_color="FDEBD0", fill_type="solid")

        ws.row_dimensions[data_row].height = 18
        data_row += 1

    # ---- Аркуш ТО ----
    ws_mnt = wb.create_sheet("Технічне обслуговування")
    stats = db.get_maintenance_stats(generator_id)
    mnt_history = db.get_maintenance_history(generator_id, 100)

    ws_mnt["A1"] = f"Технічне обслуговування — {gen_name}"
    ws_mnt["A1"].font = Font(bold=True, size=13)
    ws_mnt.merge_cells("A1:E1")
    ws_mnt["A1"].alignment = Alignment(horizontal="center")
    ws_mnt["A1"].fill = PatternFill(start_color="EAF2FB", end_color="EAF2FB", fill_type="solid")

    ws_mnt["A3"] = "Мотогодини (загалом):"
    ws_mnt["B3"] = f"{float(stats.get('total_hours', 0)):.1f} год"
    ws_mnt["A3"].font = BOLD_FONT
    ws_mnt["B3"].font = Font(size=11)

    mnt_col_hdrs = ["Дата", "Тип ТО", "Мотогодини на момент ТО", "Виконав", "Примітки"]
    for ci, h in enumerate(mnt_col_hdrs, start=1):
        c = ws_mnt.cell(row=5, column=ci, value=h)
        _style_header(c)

    ws_mnt.column_dimensions["A"].width = 14
    ws_mnt.column_dimensions["B"].width = 22
    ws_mnt.column_dimensions["C"].width = 26
    ws_mnt.column_dimensions["D"].width = 20
    ws_mnt.column_dimensions["E"].width = 20

    mnt_map = {"oil": "Заміна мастила", "spark": "Заміна свічок", "maintenance": "Планове ТО"}
    for ri, rec in enumerate(mnt_history, start=6):
        rec_id, date_s, action, hours, admin_name, *_ = rec
        ws_mnt.cell(row=ri, column=1, value=date_s)
        ws_mnt.cell(row=ri, column=2, value=mnt_map.get(action, action))
        ws_mnt.cell(row=ri, column=3, value=f"{float(hours):.1f} год")
        ws_mnt.cell(row=ri, column=4, value=admin_name or "—")
        for ci in range(1, 5):
            _style_data(ws_mnt.cell(row=ri, column=ci))

    return wb


async def api_report_excel(request: web.Request) -> web.Response:
    """GET /api/report/excel?days=30&generator=main — завантаження Excel-звіту.

    Параметр ``generator`` може бути ``main``, ``emergency`` або ``all``
    (за замовчуванням — активний генератор).
    """
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

    generator_param = (request.query.get("generator") or "").strip().lower()
    if generator_param not in ("main", "emergency"):
        generator_param = db.get_active_generator()

    try:
        now = datetime.now(config.KYIV)
        gen_name = db.get_generator_name(generator_param)
        wb = _build_daily_report_wb(generator_param, period_days, now)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        safe_gen = "основний" if generator_param == "main" else "аварійний"
        filename = f"звіт_{safe_gen}_{now.strftime('%Y%m%d_%H%M')}.xlsx"
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name, "export_excel",
            f"Експорт Excel-звіту: {gen_name} за {period_days} дн.",
            target_entity=f"generator:{generator_param}",
            new_value={"days": period_days, "generator": generator_param},
        )
        return web.Response(
            body=buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("api_report_excel error")
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# Admin CRUD: drivers & personnel
# ---------------------------------------------------------------------------

async def api_admin_drivers_list(request: web.Request) -> web.Response:
    """GET /api/admin/drivers — список водіїв (лише для адмінів)."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)
    try:
        drivers = db.get_drivers()
        return web.json_response({"drivers": list(drivers) if drivers else []})
    except Exception as e:
        logger.exception("api_admin_drivers_list error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_drivers_add(request: web.Request) -> web.Response:
    """POST /api/admin/drivers — додати водія."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    name = (body.get("name") or "").strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        return web.json_response({"error": "Невірне ім'я водія (1–100 символів)"}, status=400)

    try:
        ok = db.add_driver(name)
        if not ok:
            return web.json_response({"error": f"Водій «{name}» вже існує"}, status=409)
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name, "driver_add",
            f"Додано водія «{name}»",
            target_entity=f"driver:{name}",
            new_value=name,
        )
        return web.json_response({"ok": True, "message": f"Водія «{name}» додано"})
    except Exception as e:
        logger.exception("api_admin_drivers_add error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_drivers_delete(request: web.Request) -> web.Response:
    """DELETE /api/admin/drivers — видалити водія."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    name = (body.get("name") or "").strip()
    if not name:
        return web.json_response({"error": "Ім'я водія обов'язкове"}, status=400)

    try:
        ok = db.delete_driver(name)
        if not ok:
            return web.json_response({"error": f"Водія «{name}» не знайдено"}, status=404)
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name, "driver_delete",
            f"Видалено водія «{name}»",
            target_entity=f"driver:{name}",
            old_value=name,
        )
        return web.json_response({"ok": True, "message": f"Водія «{name}» видалено"})
    except Exception as e:
        logger.exception("api_admin_drivers_delete error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_personnel_list(request: web.Request) -> web.Response:
    """GET /api/admin/personnel — список персоналу (лише для адмінів)."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)
    try:
        names = db.get_personnel_names()
        users_with_p = db.get_all_users_with_personnel()
        users_list = [
            {"user_id": row[0], "full_name": row[1] or "", "personnel": row[2] or ""}
            for row in users_with_p
        ]
        return web.json_response({"personnel": names, "users": users_list})
    except Exception as e:
        logger.exception("api_admin_personnel_list error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_personnel_add(request: web.Request) -> web.Response:
    """POST /api/admin/personnel — додати ПІБ персоналу."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    name = (body.get("name") or "").strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        return web.json_response({"error": "Невірне ім'я (1–100 символів)"}, status=400)

    try:
        ok = db.add_personnel_name(name)
        if not ok:
            return web.json_response({"error": f"Персонал «{name}» вже існує"}, status=409)
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name, "personnel_add",
            f"Додано персонал «{name}»",
            target_entity=f"personnel:{name}",
            new_value=name,
        )
        return web.json_response({"ok": True, "message": f"Персонал «{name}» додано"})
    except Exception as e:
        logger.exception("api_admin_personnel_add error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_personnel_delete(request: web.Request) -> web.Response:
    """DELETE /api/admin/personnel — видалити ПІБ персоналу."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    name = (body.get("name") or "").strip()
    if not name:
        return web.json_response({"error": "Ім'я обов'язкове"}, status=400)

    try:
        ok = db.delete_personnel_name(name)
        if not ok:
            return web.json_response({"error": f"Персонал «{name}» не знайдено"}, status=404)
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name, "personnel_delete",
            f"Видалено персонал «{name}»",
            target_entity=f"personnel:{name}",
            old_value=name,
        )
        return web.json_response({"ok": True, "message": f"Персонал «{name}» видалено"})
    except Exception as e:
        logger.exception("api_admin_personnel_delete error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_personnel_assign(request: web.Request) -> web.Response:
    """POST /api/admin/personnel/assign — прив'язати персонал до Telegram-користувача."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Невірний JSON"}, status=400)

    try:
        target_user_id = int(body.get("user_id", 0))
    except (TypeError, ValueError):
        return web.json_response({"error": "Невірний user_id"}, status=400)

    personnel_name = (body.get("personnel") or "").strip() or None

    if not target_user_id:
        return web.json_response({"error": "user_id обов'язковий"}, status=400)

    try:
        old_personnel = db.get_personnel_for_user(target_user_id)
        db.set_personnel_for_user(target_user_id, personnel_name)
        admin_id, admin_name = _get_admin_info(user)
        if personnel_name:
            msg = f"Прив'язано: user {target_user_id} → «{personnel_name}»"
        else:
            msg = f"Прив'язку для user {target_user_id} знято"
        db.log_admin_action(
            admin_id, admin_name, "personnel_assign",
            msg,
            target_entity=f"user:{target_user_id}",
            old_value=old_personnel,
            new_value=personnel_name,
        )
        return web.json_response({"ok": True, "message": msg})
    except Exception as e:
        logger.exception("api_admin_personnel_assign error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_sync(request: web.Request) -> web.Response:
    """POST /api/admin/sync — запуск синхронізації з Google Sheets (експорт)."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        from services.sheets_export import full_export
        result = full_export()
        updated = result.get("updated", [])
        skipped = result.get("skipped", [])
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name, "export_sheets",
            f"Синхронізація з Google Sheets: {len(updated)} дн. оновлено",
            new_value={"updated": len(updated), "skipped": len(skipped)},
        )
        return web.json_response({
            "ok": True,
            "message": f"Синхронізовано: {len(updated)} дн., пропущено: {len(skipped)} дн.",
            "updated": updated,
            "skipped": skipped,
        })
    except Exception as e:
        logger.exception("api_admin_sync error")
        return web.json_response({"error": f"Помилка синхронізації: {e}"}, status=500)


# ---------------------------------------------------------------------------
# Admin Audit Log endpoints
# ---------------------------------------------------------------------------

async def api_admin_audit(request: web.Request) -> web.Response:
    """GET /api/admin/audit — журнал дій адміністраторів.

    Query params:
        limit      (int, default 50, max 200)
        offset     (int, default 0)
        action_type (str, optional filter)
        admin_id   (int, optional filter by admin user ID)
        date_from  (str YYYY-MM-DD, optional)
        date_to    (str YYYY-MM-DD, optional)
    """
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        limit = min(int(request.query.get("limit", "50")), 200)
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = max(int(request.query.get("offset", "0")), 0)
    except (TypeError, ValueError):
        offset = 0

    action_type = request.query.get("action_type", "").strip()
    date_from = request.query.get("date_from", "").strip()
    date_to = request.query.get("date_to", "").strip()
    try:
        admin_filter = int(request.query.get("admin_id", "0"))
    except (TypeError, ValueError):
        admin_filter = 0

    try:
        rows = db.get_audit_logs(
            limit=limit, offset=offset,
            action_type=action_type, admin_user_id=admin_filter,
            date_from=date_from, date_to=date_to,
        )
        total = db.count_audit_logs(
            action_type=action_type, admin_user_id=admin_filter,
            date_from=date_from, date_to=date_to,
        )
        entries = [
            {
                "id": r[0],
                "timestamp": r[1],
                "admin_user_id": r[2],
                "admin_name": r[3],
                "action_type": r[4],
                "action_description": r[5],
                "target_entity": r[6],
                "old_value": r[7],
                "new_value": r[8],
                "success": bool(r[9]),
            }
            for r in rows
        ]
        return web.json_response({
            "entries": entries,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        logger.exception("api_admin_audit error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_audit_export(request: web.Request) -> web.Response:
    """GET /api/admin/audit/export — експорт журналу дій у Excel."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    if not EXCEL_AVAILABLE:
        return web.json_response({"error": "Модуль openpyxl не встановлено"}, status=500)

    action_type = request.query.get("action_type", "").strip()
    date_from = request.query.get("date_from", "").strip()
    date_to = request.query.get("date_to", "").strip()
    try:
        admin_filter = int(request.query.get("admin_id", "0"))
    except (TypeError, ValueError):
        admin_filter = 0

    try:
        rows = db.get_audit_logs(
            limit=5000, offset=0,
            action_type=action_type, admin_user_id=admin_filter,
            date_from=date_from, date_to=date_to,
        )

        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "Журнал дій"

        headers = ["#", "Час", "Адмін ID", "Адмін", "Тип дії",
                   "Опис", "Об'єкт", "Старе значення", "Нове значення", "Успішно"]
        header_fill = PatternFill(start_color="2481CC", end_color="2481CC", fill_type="solid")
        for ci, h in enumerate(headers, start=1):
            c = ws.cell(row=1, column=ci, value=h)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = header_fill
            c.alignment = Alignment(horizontal="center")

        col_widths = [6, 20, 12, 20, 18, 40, 25, 20, 20, 10]
        from openpyxl.utils import get_column_letter as _gcl
        for ci, w in enumerate(col_widths, start=1):
            ws.column_dimensions[_gcl(ci)].width = w

        for ri, r in enumerate(rows, start=2):
            ws.cell(row=ri, column=1, value=r[0])
            ws.cell(row=ri, column=2, value=r[1])
            ws.cell(row=ri, column=3, value=r[2])
            ws.cell(row=ri, column=4, value=r[3] or "")
            ws.cell(row=ri, column=5, value=r[4] or "")
            ws.cell(row=ri, column=6, value=r[5] or "")
            ws.cell(row=ri, column=7, value=r[6] or "")
            ws.cell(row=ri, column=8, value=r[7] or "")
            ws.cell(row=ri, column=9, value=r[8] or "")
            ws.cell(row=ri, column=10, value="✅" if r[9] else "❌")

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        now = datetime.now(config.KYIV)
        filename = f"audit_log_{now.strftime('%Y%m%d_%H%M')}.xlsx"
        return web.Response(
            body=buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("api_admin_audit_export error")
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# Backup endpoints
# ---------------------------------------------------------------------------

async def api_admin_backups_list(request: web.Request) -> web.Response:
    """GET /api/admin/backups — список резервних копій."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        from backup import list_backups, DEFAULT_BACKUP_DIR
        backups = list_backups()
        return web.json_response({"backups": backups, "count": len(backups)})
    except Exception as e:
        logger.exception("api_admin_backups_list error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_backup_create(request: web.Request) -> web.Response:
    """POST /api/admin/backup — створити резервну копію вручну."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    try:
        from backup import create_backup
        backup_path = create_backup()
        size_kb = round(backup_path.stat().st_size / 1024, 1)
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id, admin_name, "backup_create",
            f"Створено резервну копію вручну: {backup_path.name} ({size_kb} KB)",
            target_entity=backup_path.name,
            new_value={"filename": backup_path.name, "size_kb": size_kb},
        )
        return web.json_response({
            "ok": True,
            "filename": backup_path.name,
            "size_kb": size_kb,
            "message": f"Резервну копію створено: {backup_path.name}",
        })
    except Exception as e:
        logger.exception("api_admin_backup_create error")
        return web.json_response({"error": str(e)}, status=500)


async def api_admin_backup_download(request: web.Request) -> web.Response:
    """GET /api/admin/backup/download/{filename} — завантажити резервну копію."""
    user = _extract_user(request)
    if not _is_admin(user):
        return web.json_response({"error": "Тільки для адміністраторів"}, status=403)

    filename = request.match_info.get("filename", "")
    # Security: only allow safe filenames (no path traversal)
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return web.json_response({"error": "Невірне ім'я файлу"}, status=400)
    if not filename.startswith("backup_") or not filename.endswith(".sql.gz"):
        return web.json_response({"error": "Невірний формат файлу"}, status=400)

    try:
        from backup import DEFAULT_BACKUP_DIR
        backup_path = DEFAULT_BACKUP_DIR / filename
        if not backup_path.exists():
            return web.json_response({"error": "Файл не знайдено"}, status=404)

        with open(backup_path, "rb") as f:
            data = f.read()

        return web.Response(
            body=data,
            content_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("api_admin_backup_download error")
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# Статичні файли та додаток
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    """Створює aiohttp-додаток з API та статичними файлами."""
    app = web.Application(middlewares=[rate_limit_middleware, cors_middleware])

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
    # Admin management endpoints
    app.router.add_get("/api/admin/drivers", api_admin_drivers_list)
    app.router.add_post("/api/admin/drivers", api_admin_drivers_add)
    app.router.add_delete("/api/admin/drivers", api_admin_drivers_delete)
    app.router.add_get("/api/admin/personnel", api_admin_personnel_list)
    app.router.add_post("/api/admin/personnel", api_admin_personnel_add)
    app.router.add_delete("/api/admin/personnel", api_admin_personnel_delete)
    app.router.add_post("/api/admin/personnel/assign", api_admin_personnel_assign)
    app.router.add_post("/api/admin/sync", api_admin_sync)
    # Audit log endpoints
    app.router.add_get("/api/admin/audit", api_admin_audit)
    app.router.add_get("/api/admin/audit/export", api_admin_audit_export)
    # Backup endpoints
    app.router.add_get("/api/admin/backups", api_admin_backups_list)
    app.router.add_post("/api/admin/backup", api_admin_backup_create)
    app.router.add_get("/api/admin/backup/download/{filename}", api_admin_backup_download)

    # Статичні файли (CSS, JS)
    webapp_dir = _PROJECT_ROOT / "webapp"
    if webapp_dir.is_dir():
        app.router.add_static("/css/", webapp_dir / "css", name="css")
        app.router.add_static("/js/", webapp_dir / "js", name="js")

        # index.html — кореневий маршрут
        async def index_handler(request: web.Request) -> web.FileResponse:
            return web.FileResponse(webapp_dir / "index.html")

        async def block_handler(request: web.Request) -> web.FileResponse:
            return web.FileResponse(webapp_dir / "block.html")

        async def sw_handler(request: web.Request) -> web.FileResponse:
            return web.FileResponse(
                webapp_dir / "service-worker.js",
                headers={"Content-Type": "application/javascript"},
            )

        app.router.add_get("/", index_handler)
        app.router.add_get("/block.html", block_handler)
        app.router.add_get("/service-worker.js", sw_handler)

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
