"""Public database API facade.

This module keeps the historical import path used throughout the project:

    import database.db_api as db

Implementation is split into `database.api.*` modules.
"""

from database.api.users import register_user, get_user, get_all_users
from database.api.ui import set_ui_message, get_ui_message, clear_ui_message
from database.api.personnel import (
    set_personnel_for_user,
    get_personnel_for_user,
    get_all_users_with_personnel,
    sync_personnel_from_sheet,
    get_personnel_names,
)
from database.api.drivers import add_driver, get_drivers, sync_drivers_from_sheet, delete_driver
from database.api.state import (
    _OFFLINE_THRESHOLD_SECONDS,
    set_state,
    get_state_value,
    _conn_get_state_value,
    _conn_set_state_value,
    _conn_get_state_float,
    sheet_is_forced_offline,
    sheet_mark_ok,
    sheet_mark_fail,
    sheet_force_offline,
    sheet_force_online,
    sheet_check_offline,
    sheet_is_offline,
    get_state,
)
from database.api.fuel import update_fuel
from database.api.logs import (
    get_today_completed_shifts,
    get_last_logs,
    add_log,
    try_start_shift,
    try_stop_shift,
    get_unsynced,
    mark_synced,
    get_logs_for_period,
    get_refills_for_date,
)
from database.api.maintenance import update_hours, set_total_hours, record_maintenance
from database.api.schedule import toggle_schedule, set_schedule_range, get_schedule


__all__ = [
    # users
    "register_user",
    "get_user",
    "get_all_users",
    # ui
    "set_ui_message",
    "get_ui_message",
    "clear_ui_message",
    # personnel
    "set_personnel_for_user",
    "get_personnel_for_user",
    "get_all_users_with_personnel",
    "sync_personnel_from_sheet",
    "get_personnel_names",
    # drivers
    "add_driver",
    "get_drivers",
    "sync_drivers_from_sheet",
    "delete_driver",
    # state
    "_OFFLINE_THRESHOLD_SECONDS",
    "set_state",
    "get_state_value",
    "_conn_get_state_value",
    "_conn_set_state_value",
    "_conn_get_state_float",
    "sheet_is_forced_offline",
    "sheet_mark_ok",
    "sheet_mark_fail",
    "sheet_force_offline",
    "sheet_force_online",
    "sheet_check_offline",
    "sheet_is_offline",
    "get_state",
    # fuel
    "update_fuel",
    # logs
    "get_today_completed_shifts",
    "get_last_logs",
    "add_log",
    "try_start_shift",
    "try_stop_shift",
    "get_unsynced",
    "mark_synced",
    "get_logs_for_period",
    "get_refills_for_date",
    # maintenance
    "update_hours",
    "set_total_hours",
    "record_maintenance",
    # schedule
    "toggle_schedule",
    "set_schedule_range",
    "get_schedule",
]
