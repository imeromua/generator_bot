"""
Telegram Mini App — backward-compatibility shim.

The actual implementation has been moved to the webapp/ package.
This module re-exports everything for backward compatibility.
"""

import os
import sys
import logging
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import database.models as db_models  # noqa: E402

from webapp.app import create_app  # noqa: E402
from webapp.utils.validation import (  # noqa: E402, F401
    validate_init_data as _validate_init_data,
    extract_user as _extract_user,
)
from webapp.utils.permissions import is_admin as _is_admin  # noqa: E402, F401
from webapp.services.analytics_service import _safe_round, _build_daily_stats  # noqa: E402, F401
from webapp.api.status import (  # noqa: E402, F401
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
from webapp.api.events import api_events  # noqa: E402, F401
from webapp.api.actions import api_action_start, api_action_stop, api_action_refill  # noqa: E402, F401
from webapp.api.maintenance import (  # noqa: E402, F401
    api_maintenance,
    api_maintenance_perform,
    api_maintenance_set_hours,
    api_fuel_set,
)
from webapp.api.admin import (  # noqa: E402, F401
    api_admin_drivers_list,
    api_admin_drivers_add,
    api_admin_drivers_delete,
    api_admin_personnel_list,
    api_admin_personnel_add,
    api_admin_personnel_delete,
    api_admin_personnel_assign,
    api_admin_sync,
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
from webapp.api.notifications import (  # noqa: E402, F401
    api_notifications_get,
    api_notifications_set,
    api_notifications_test,
    api_notifications_quiet_hours,
)
from webapp.api.fuel_orders import (  # noqa: E402, F401
    api_fuel_orders_list,
    api_fuel_orders_create,
    api_fuel_orders_update,
)
from webapp.api.shifts import api_shifts_get, api_shifts_set, api_shifts_auto, api_shifts_analytics  # noqa: E402, F401
from webapp.api.analytics import (  # noqa: E402, F401
    api_analytics_kpi,
    api_analytics_fuel_timeline,
    api_analytics_motor_hours,
    api_analytics_efficiency,
    api_analytics_calendar,
    api_analytics_trends,
    api_analytics_forecast,
)
from webapp.api.reports import api_report_excel, api_report_excel_v2  # noqa: E402, F401

logger = logging.getLogger(__name__)


def main():
    """Entry point — starts the web server."""
    import uvicorn
    import config

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("🔧 Ініціалізація бази даних...")
    db_models.init_db()

    port = int(os.getenv("WEBAPP_PORT", "8080"))
    host = os.getenv("WEBAPP_HOST", "0.0.0.0")

    app = create_app()

    logger.info(f"🌐 Mini App сервер запускається на http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
