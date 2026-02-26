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
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote

from aiohttp import web

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
    """Витягує та валідує користувача з заголовка X-Telegram-Init-Data."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
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
# Статичні файли та додаток
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    """Створює aiohttp-додаток з API та статичними файлами."""
    app = web.Application(middlewares=[cors_middleware])

    # API маршрути
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/schedule", api_schedule)
    app.router.add_get("/api/schedule/week", api_schedule_week)
    app.router.add_get("/api/events", api_events)
    app.router.add_get("/api/maintenance", api_maintenance)

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
