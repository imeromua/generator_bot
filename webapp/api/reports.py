"""Report generation API endpoints."""

import io
import logging
from datetime import datetime
from fastapi import Request
from fastapi.responses import JSONResponse, Response
import config
import database.db_api as db
from webapp.utils import validation as _validation_mod
from webapp.utils import permissions as _permissions_mod
from webapp.utils.db_helpers import get_admin_info as _get_admin_info
from webapp.services.reports_service import _build_daily_report_wb, EXCEL_AVAILABLE
from reports.excel_reports import generate_excel_report, EXCEL_AVAILABLE as _EXCEL_RPT_AVAILABLE

logger = logging.getLogger(__name__)


async def api_report_excel(request: Request):
    """GET /api/report/excel?days=30&generator=main — завантаження Excel-звіту.

    Параметр ``generator`` може бути ``main``, ``emergency`` або ``all``
    (за замовчуванням — активний генератор).
    """
    user = _validation_mod.extract_user(request)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)

    if not EXCEL_AVAILABLE:
        return JSONResponse(content={"error": "Модуль openpyxl не встановлено"}, status_code=500)

    try:
        period_days = int(request.query_params.get("days", "30"))
        if period_days < 1:
            period_days = 30
        if period_days > 365:
            period_days = 365
    except (ValueError, TypeError):
        period_days = 30

    generator_param = (request.query_params.get("generator") or "").strip().lower()
    if generator_param not in ("main", "emergency"):
        generator_param = db.get_active_generator()

    try:
        now = datetime.now(config.KYIV)
        gen_name = db.get_generator_name(generator_param)
        wb = _build_daily_report_wb(generator_param, period_days, now)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        safe_gen = "main" if generator_param == "main" else "backup"
        filename = f"report_{safe_gen}_{now.strftime('%Y%m%d_%H%M')}.xlsx"
        admin_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            admin_id,
            admin_name,
            "export_excel",
            f"Експорт Excel-звіту: {gen_name} за {period_days} дн.",
            target_entity=f"generator:{generator_param}",
            new_value={"days": period_days, "generator": generator_param},
        )
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as e:
        logger.exception("api_report_excel error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_report_excel_v2(request: Request):
    """GET /api/report/excel/v2?type=quick&days=30&generator=main — enhanced Excel report."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    if not _EXCEL_RPT_AVAILABLE:
        return JSONResponse(content={"error": "Модуль openpyxl не встановлено"}, status_code=500)

    try:
        report_type = request.query_params.get("type", "quick")
        valid_types = ("quick", "detailed", "personnel", "technical", "financial")
        if report_type not in valid_types:
            return JSONResponse(content={"error": "Невірний тип звіту"}, status_code=400)

        days = int(request.query_params.get("days", "30"))
        days = max(1, min(days, 365))
        gen_id = (request.query_params.get("generator") or "").strip().lower() or None
        if gen_id not in ("main", "emergency"):
            gen_id = None

        now = datetime.now(config.KYIV)
        excel_bytes = generate_excel_report(report_type, days, gen_id)

        filename = f"generator_report_{report_type}_{now.strftime('%Y%m%d')}.xlsx"
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("api_report_excel_v2 error")
        return JSONResponse(content={"error": str(e)}, status_code=500)
