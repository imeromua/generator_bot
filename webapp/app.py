"""Application factory for the Telegram Mini App web server."""

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi import Request
from fastapi.staticfiles import StaticFiles

import database.models as db_models
from webapp.middleware.rate_limit import RateLimitMiddleware
from get_build_version import BUILD_VERSION

from webapp.api.status import (
    api_status,
    api_schedule,
    api_schedule_week,
    api_user_role,
    api_drivers,
    api_generators,
    api_personnel_me,
    api_schedule_toggle,
    api_generator_switch,
)
from webapp.api.events import api_events
from webapp.api.actions import api_action_start, api_action_stop, api_action_refill
from webapp.api.maintenance import api_maintenance, api_maintenance_perform, api_maintenance_set_hours, api_fuel_set
from webapp.api.admin import (
    api_admin_drivers_list,
    api_admin_drivers_add,
    api_admin_drivers_delete,
    api_admin_personnel_list,
    api_admin_personnel_add,
    api_admin_personnel_delete,
    api_admin_personnel_assign,
    api_admin_sync,
    api_admin_sync_preview,
    api_admin_sync_apply,
    api_admin_audit,
    api_admin_audit_export,
    api_admin_config_get,
    api_admin_config_set_generator,
    api_admin_config_set_global,
    api_admin_config_history,
    api_admin_backups_list,
    api_admin_backup_create,
    api_admin_backup_download,
)
from webapp.api.notifications import (
    api_notifications_get,
    api_notifications_set,
    api_notifications_test,
    api_notifications_quiet_hours,
)
from webapp.api.fuel_orders import api_fuel_orders_list, api_fuel_orders_create, api_fuel_orders_update
from webapp.api.shifts import api_shifts_get, api_shifts_set, api_shifts_auto, api_shifts_analytics
from webapp.api.analytics import (
    api_analytics_kpi,
    api_analytics_fuel_timeline,
    api_analytics_motor_hours,
    api_analytics_efficiency,
    api_analytics_calendar,
    api_analytics_trends,
    api_analytics_forecast,
)
from webapp.api.reports import api_report_excel, api_report_excel_v2
from webapp.api.users import (
    api_admin_users_list,
    api_admin_users_update_role,
    api_admin_users_block,
    api_admin_users_unblock,
    api_admin_users_delete,
)

from servicedesk.auth_router import router as sd_auth_router
from servicedesk.static_router import mount_sd_static, router as sd_static_router

import config

logger = logging.getLogger(__name__)

_webapp_dir = Path(__file__).resolve().parent
_sw_path = _webapp_dir / "service-worker.js"
try:
    with open(_sw_path, 'r', encoding='utf-8') as f:
        _sw_raw: str | None = f.read()
except FileNotFoundError:
    _sw_raw = None

_sw_content = re.sub(
    r"(const CACHE_VERSION\s*=\s*')[^']*(')",
    rf"\g<1>{BUILD_VERSION}\2",
    _sw_raw or "",
)


async def index_handler(request: Request):
    return FileResponse(str(_webapp_dir / "index.html"))


async def block_handler(request: Request):
    return FileResponse(str(_webapp_dir / "block.html"))


async def settings_handler(request: Request):
    return FileResponse(str(_webapp_dir / "settings.html"))


async def sw_handler(request: Request):
    """Serve service-worker.js with dynamic cache version injected."""
    if _sw_raw is None:
        return Response(content='Service Worker not found', status_code=404, media_type='text/plain')
    return Response(
        content=_sw_content,
        media_type='application/javascript',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Service-Worker-Allowed': '/',
        },
    )


@asynccontextmanager
async def _webapp_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    try:
        db_models.init_db()
        logger.info("✅ [lifespan] DB initialised")
    except Exception:
        logger.exception("❌ [lifespan] DB init failed")
        raise
    yield
    try:
        from database.models import close_postgres_pool

        close_postgres_pool()
        logger.info("✅ [lifespan] DB pool closed")
    except Exception:
        logger.warning("⚠️  [lifespan] Error closing DB pool (ignored)")


def create_app() -> FastAPI:
    """Creates the FastAPI application with all API routes and static files."""
    _debug = getattr(config, "DEBUG", False)
    app = FastAPI(
        title="Generator Bot WebApp",
        version=BUILD_VERSION,
        docs_url="/api/docs" if _debug else None,
        redoc_url="/api/redoc" if _debug else None,
        lifespan=_webapp_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)

    # ServiceDesk auth router (SD-2)
    app.include_router(sd_auth_router)

    # Digital Asset Links endpoint for Android TWA (SD-4)
    app.include_router(sd_static_router)

    app.add_api_route("/api/status", api_status, methods=["GET"])
    app.add_api_route("/api/schedule", api_schedule, methods=["GET"])
    app.add_api_route("/api/schedule/week", api_schedule_week, methods=["GET"])
    app.add_api_route("/api/events", api_events, methods=["GET"])
    app.add_api_route("/api/maintenance", api_maintenance, methods=["GET"])
    app.add_api_route("/api/user/role", api_user_role, methods=["GET"])
    app.add_api_route("/api/drivers", api_drivers, methods=["GET"])
    app.add_api_route("/api/generators", api_generators, methods=["GET"])
    app.add_api_route("/api/personnel/me", api_personnel_me, methods=["GET"])
    app.add_api_route("/api/report/excel", api_report_excel, methods=["GET"])

    app.add_api_route("/api/action/start", api_action_start, methods=["POST"])
    app.add_api_route("/api/action/stop", api_action_stop, methods=["POST"])
    app.add_api_route("/api/action/refill", api_action_refill, methods=["POST"])
    app.add_api_route("/api/schedule/toggle", api_schedule_toggle, methods=["POST"])
    app.add_api_route("/api/generator/switch", api_generator_switch, methods=["POST"])
    app.add_api_route("/api/maintenance/perform", api_maintenance_perform, methods=["POST"])
    app.add_api_route("/api/maintenance/set-hours", api_maintenance_set_hours, methods=["POST"])
    app.add_api_route("/api/fuel/set", api_fuel_set, methods=["POST"])

    app.add_api_route("/api/admin/drivers", api_admin_drivers_list, methods=["GET"])
    app.add_api_route("/api/admin/drivers", api_admin_drivers_add, methods=["POST"])
    app.add_api_route("/api/admin/drivers", api_admin_drivers_delete, methods=["DELETE"])
    app.add_api_route("/api/admin/personnel", api_admin_personnel_list, methods=["GET"])
    app.add_api_route("/api/admin/personnel", api_admin_personnel_add, methods=["POST"])
    app.add_api_route("/api/admin/personnel", api_admin_personnel_delete, methods=["DELETE"])
    app.add_api_route("/api/admin/personnel/assign", api_admin_personnel_assign, methods=["POST"])
    app.add_api_route("/api/admin/sync", api_admin_sync, methods=["POST"])
    app.add_api_route("/api/admin/sync/preview", api_admin_sync_preview, methods=["GET"])
    app.add_api_route("/api/admin/sync/apply", api_admin_sync_apply, methods=["POST"])
    app.add_api_route("/api/admin/audit", api_admin_audit, methods=["GET"])
    app.add_api_route("/api/admin/audit/export", api_admin_audit_export, methods=["GET"])
    app.add_api_route("/api/admin/config", api_admin_config_get, methods=["GET"])
    app.add_api_route("/api/admin/config/generator", api_admin_config_set_generator, methods=["POST"])
    app.add_api_route("/api/admin/config/global", api_admin_config_set_global, methods=["POST"])
    app.add_api_route("/api/admin/config/history", api_admin_config_history, methods=["GET"])
    app.add_api_route("/api/admin/backups", api_admin_backups_list, methods=["GET"])
    app.add_api_route("/api/admin/backup", api_admin_backup_create, methods=["POST"])
    app.add_api_route("/api/admin/backup/download/{filename}", api_admin_backup_download, methods=["GET"])

    app.add_api_route("/api/admin/users", api_admin_users_list, methods=["GET"])
    app.add_api_route("/api/admin/users/{user_id}/role", api_admin_users_update_role, methods=["PUT"])
    app.add_api_route("/api/admin/users/{user_id}/block", api_admin_users_block, methods=["PUT"])
    app.add_api_route("/api/admin/users/{user_id}/unblock", api_admin_users_unblock, methods=["PUT"])
    app.add_api_route("/api/admin/users/{user_id}", api_admin_users_delete, methods=["DELETE"])

    app.add_api_route("/api/notifications/preferences", api_notifications_get, methods=["GET"])
    app.add_api_route("/api/notifications/preferences", api_notifications_set, methods=["POST"])
    app.add_api_route("/api/notifications/test", api_notifications_test, methods=["POST"])
    app.add_api_route("/api/notifications/quiet-hours", api_notifications_quiet_hours, methods=["POST"])

    app.add_api_route("/api/fuel/orders", api_fuel_orders_list, methods=["GET"])
    app.add_api_route("/api/fuel/orders", api_fuel_orders_create, methods=["POST"])
    app.add_api_route("/api/fuel/orders/update", api_fuel_orders_update, methods=["POST"])

    app.add_api_route("/api/shifts/schedule", api_shifts_get, methods=["GET"])
    app.add_api_route("/api/shifts/schedule", api_shifts_set, methods=["POST"])
    app.add_api_route("/api/shifts/auto", api_shifts_auto, methods=["POST"])
    app.add_api_route("/api/shifts/analytics", api_shifts_analytics, methods=["GET"])

    app.add_api_route("/api/analytics/kpi", api_analytics_kpi, methods=["GET"])
    app.add_api_route("/api/analytics/fuel-timeline", api_analytics_fuel_timeline, methods=["GET"])
    app.add_api_route("/api/analytics/motor-hours", api_analytics_motor_hours, methods=["GET"])
    app.add_api_route("/api/analytics/efficiency", api_analytics_efficiency, methods=["GET"])
    app.add_api_route("/api/analytics/calendar", api_analytics_calendar, methods=["GET"])
    app.add_api_route("/api/analytics/trends", api_analytics_trends, methods=["GET"])
    app.add_api_route("/api/analytics/forecast", api_analytics_forecast, methods=["GET"])
    app.add_api_route("/api/report/excel/v2", api_report_excel_v2, methods=["GET"])

    if _webapp_dir.is_dir():
        app.add_api_route("/service-worker.js", sw_handler, methods=["GET"])
        app.add_api_route("/", index_handler, methods=["GET"])
        app.add_api_route("/block.html", block_handler, methods=["GET"])
        app.add_api_route("/settings", settings_handler, methods=["GET"])

        css_dir = _webapp_dir / "css"
        js_dir = _webapp_dir / "js"
        if css_dir.is_dir():
            app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
        if js_dir.is_dir():
            app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")

    # ServiceDesk SPA static files (mounted at /sd)
    mount_sd_static(app)

    return app


__all__ = ["create_app"]
