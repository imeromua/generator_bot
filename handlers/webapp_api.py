"""REST API для Telegram Mini App.

Забезпечує HTTP-ендпоінти для отримання даних бота з веб-інтерфейсу.
Аутентифікація через перевірку Telegram WebApp initData (HMAC-SHA256).
"""

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qs, unquote

from aiohttp import web

import config
import database.db_api as db

logger = logging.getLogger(__name__)


def _validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Перевіряє автентичність initData від Telegram WebApp.

    Повертає dict з даними користувача або None, якщо перевірка не пройшла.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        received_hash = parsed.get("hash", [""])[0]
        if not received_hash:
            return None

        # Створюємо data_check_string (всі поля, крім hash, в алфавітному порядку)
        items = []
        for key in sorted(parsed.keys()):
            if key == "hash":
                continue
            items.append(f"{key}={parsed[key][0]}")
        data_check_string = "\n".join(items)

        # Обчислюємо секретний ключ
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
        ).digest()

        # Обчислюємо хеш
        computed_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        # Перевіряємо auth_date (не старше 24 годин)
        auth_date = int(parsed.get("auth_date", ["0"])[0])
        if abs(time.time() - auth_date) > 86400:
            return None

        # Парсимо дані користувача
        user_str = parsed.get("user", [""])[0]
        if user_str:
            return json.loads(unquote(user_str))

        return None
    except Exception as e:
        logger.warning(f"initData validation error: {e}")
        return None


def _get_user_from_request(request: web.Request) -> dict | None:
    """Отримує та перевіряє дані користувача з заголовка запиту."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        return None
    return _validate_init_data(init_data, config.BOT_TOKEN)


def _is_admin(user_id: int) -> bool:
    """Перевіряє, чи є користувач адміністратором."""
    return user_id in config.ADMIN_IDS


def _shift_name(code: str) -> str:
    """Повертає людськочитабельну назву зміни."""
    return {
        "m_start": "🌅 Зміна 1",
        "d_start": "☀️ Зміна 2",
        "e_start": "🌙 Зміна 3",
        "x_start": "⚡ Екстра",
        "none": "—",
    }.get(code, code)


def _event_icon(event_type: str) -> str:
    """Повертає іконку для типу події."""
    icons = {
        "m_start": "🌅", "m_end": "🏁",
        "d_start": "☀️", "d_end": "🏁",
        "e_start": "🌙", "e_end": "🏁",
        "x_start": "⚡", "x_end": "🏁",
        "refill": "⛽",
        "oil": "🛢", "spark": "🕯", "maintenance": "🔧",
        "sync": "🔄",
        "corr_fuel_set": "📝", "corr_hours_set": "📝",
    }
    return icons.get(event_type, "📋")


async def api_status(request: web.Request) -> web.Response:
    """GET /api/status — стан генератора."""
    user = _get_user_from_request(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        state = db.get_state()
        active_gen = db.get_active_generator()
        gen_stats = db.get_generator_stats(active_gen)
        gen_name = db.get_generator_name(active_gen)
        completed = list(db.get_today_completed_shifts())
        is_admin = _is_admin(user.get("id", 0))

        return web.json_response({
            "status": state.get("status", "OFF"),
            "active_shift": state.get("active_shift", "none"),
            "active_shift_name": _shift_name(state.get("active_shift", "none")),
            "start_time": state.get("start_time", ""),
            "current_fuel": round(state.get("current_fuel", 0.0), 1),
            "total_hours": round(gen_stats.get("total_hours", 0.0), 1),
            "active_generator": active_gen,
            "generator_name": gen_name,
            "completed_shifts": completed,
            "is_admin": is_admin,
            "fuel_consumption": round(db.get_fuel_consumption_rate(), 2),
        })
    except Exception as e:
        logger.error(f"API status error: {e}", exc_info=True)
        return web.json_response({"error": "internal"}, status=500)


async def api_schedule(request: web.Request) -> web.Response:
    """GET /api/schedule — графік відключень на сьогодні."""
    user = _get_user_from_request(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        from datetime import datetime
        today = datetime.now(config.KYIV).strftime("%Y-%m-%d")
        schedule = db.get_schedule(today)

        hours = []
        for h in range(24):
            hours.append({
                "hour": h,
                "label": f"{h:02d}:00",
                "is_off": schedule.get(h, 0) == 1,
            })

        return web.json_response({
            "date": today,
            "hours": hours,
        })
    except Exception as e:
        logger.error(f"API schedule error: {e}", exc_info=True)
        return web.json_response({"error": "internal"}, status=500)


async def api_events(request: web.Request) -> web.Response:
    """GET /api/events — останні події."""
    user = _get_user_from_request(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        limit = int(request.query.get("limit", "20"))
        limit = min(max(1, limit), 50)
        logs = db.get_last_logs(limit=limit)

        events = []
        for row in logs:
            event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id = row
            events.append({
                "type": event_type,
                "icon": _event_icon(event_type),
                "timestamp": timestamp,
                "user": user_name or "",
                "value": value or "",
                "driver": driver_name or "",
                "receipt": receipt_number or "",
                "generator": generator_id or "main",
            })

        return web.json_response({"events": events})
    except Exception as e:
        logger.error(f"API events error: {e}", exc_info=True)
        return web.json_response({"error": "internal"}, status=500)


async def api_maintenance(request: web.Request) -> web.Response:
    """GET /api/maintenance — стан ТО."""
    user = _get_user_from_request(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        active_gen = db.get_active_generator()
        stats = db.get_maintenance_stats(active_gen)
        gen_name = db.get_generator_name(active_gen)
        history = db.get_maintenance_history(generator_id=active_gen, limit=10)

        history_items = []
        for row in history:
            _id, date, mtype, hours, admin, gen_id = row
            type_names = {"oil": "🛢 Мастило", "spark": "🕯 Свічки", "maintenance": "🔧 Планове ТО"}
            history_items.append({
                "date": date,
                "type": type_names.get(mtype, mtype),
                "hours": round(hours, 1) if hours else 0,
                "admin": admin or "",
            })

        return web.json_response({
            "generator": active_gen,
            "generator_name": gen_name,
            "oil_interval": config.OIL_CHANGE_INTERVAL,
            "spark_interval": config.SPARK_CHANGE_INTERVAL,
            "maintenance_interval": config.MAINTENANCE_INTERVAL,
            "total_hours": round(stats.get("total_hours", 0.0), 1),
            "oil_used": round(stats.get("last_oil", 0.0), 1),
            "oil_remaining": round(stats.get("oil_needed", 0.0), 1),
            "spark_used": round(stats.get("last_spark", 0.0), 1),
            "spark_remaining": round(stats.get("spark_needed", 0.0), 1),
            "maintenance_remaining": round(stats.get("maintenance_needed", 0.0), 1),
            "history": history_items,
        })
    except Exception as e:
        logger.error(f"API maintenance error: {e}", exc_info=True)
        return web.json_response({"error": "internal"}, status=500)


async def api_generators(request: web.Request) -> web.Response:
    """GET /api/generators — інформація про генератори."""
    user = _get_user_from_request(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        active = db.get_active_generator()

        main_stats = db.get_generator_stats("main")
        emergency_stats = db.get_generator_stats("emergency")

        state = db.get_state()

        return web.json_response({
            "active": active,
            "generators": {
                "main": {
                    "name": "🔋 Основний",
                    "total_hours": round(main_stats.get("total_hours", 0.0), 1),
                    "last_oil_change": round(main_stats.get("last_oil_change", 0.0), 1),
                    "last_spark_change": round(main_stats.get("last_spark_change", 0.0), 1),
                    "is_active": active == "main",
                },
                "emergency": {
                    "name": "⚠️ Аварійний",
                    "total_hours": round(emergency_stats.get("total_hours", 0.0), 1),
                    "last_oil_change": round(emergency_stats.get("last_oil_change", 0.0), 1),
                    "last_spark_change": round(emergency_stats.get("last_spark_change", 0.0), 1),
                    "is_active": active == "emergency",
                },
            },
            "current_fuel": round(state.get("current_fuel", 0.0), 1),
            "fuel_consumption": round(config.FUEL_CONSUMPTION, 2),
            "emergency_fuel_consumption": round(config.EMERGENCY_FUEL_CONSUMPTION, 2),
        })
    except Exception as e:
        logger.error(f"API generators error: {e}", exc_info=True)
        return web.json_response({"error": "internal"}, status=500)


def create_webapp_app() -> web.Application:
    """Створює aiohttp Application для Mini App."""
    import os

    app = web.Application()

    # CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
        return response

    app.middlewares.append(cors_middleware)

    # API маршрути
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/schedule", api_schedule)
    app.router.add_get("/api/events", api_events)
    app.router.add_get("/api/maintenance", api_maintenance)
    app.router.add_get("/api/generators", api_generators)

    # Статичні файли mini app
    webapp_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "webapp")
    if os.path.isdir(webapp_dir):
        app.router.add_static("/css/", os.path.join(webapp_dir, "css"), name="css")
        app.router.add_static("/js/", os.path.join(webapp_dir, "js"), name="js")

        async def serve_index(request):
            return web.FileResponse(os.path.join(webapp_dir, "index.html"))

        app.router.add_get("/", serve_index)
        app.router.add_get("/webapp", serve_index)
        app.router.add_get("/webapp/", serve_index)

    return app
