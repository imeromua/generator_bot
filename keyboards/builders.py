"""Keyboard builders for Telegram bot.

Provides inline keyboard markup builders for various bot screens.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import database.db_api as db
from datetime import datetime
import config


# --- ГОЛОВНЕ МЕНЮ ---
def main_dashboard(role: str, active_shift: str, completed_shifts: set[str]) -> InlineKeyboardMarkup:
    """Build main dashboard keyboard.

    Args:
        role: User role ('admin' or 'user')
        active_shift: Currently active shift code (e.g., 'm_start') or 'none'
        completed_shifts: Set of completed shift codes today (e.g., {'m', 'd'})

    Returns:
        InlineKeyboardMarkup with shift controls, schedule, refuel, events, and admin panel
    """
    kb: list[list[InlineKeyboardButton]] = []

    # FIX: Емодзі часу доби для кращого відображення
    def pretty(code: str) -> str:
        return {
            "m": "🌅 Зміна 1",
            "d": "☀️ Зміна 2",
            "e": "🌙 Зміна 3",
            "x": "⚡ Екстра",
        }.get(code, code.upper())

    # Telegram Bot API 9.4: colored buttons via `style` field
    # NOTE: use only known-safe styles (danger/primary); other values may be rejected by the API.
    if active_shift != 'none':
        code = active_shift.split("_")[0]
        kb.append([
            InlineKeyboardButton(
                text=f"🏁 {pretty(code)} СТОП",
                callback_data=f"{code}_end",
                style="danger",
            )
        ])
    else:
        if 'm' not in completed_shifts:
            kb.append([
                InlineKeyboardButton(
                    text=f"{pretty('m')} СТАРТ",
                    callback_data="m_start",
                    style="primary",
                )
            ])
        elif 'd' not in completed_shifts:
            kb.append([
                InlineKeyboardButton(
                    text=f"{pretty('d')} СТАРТ",
                    callback_data="d_start",
                    style="primary",
                )
            ])
        elif 'e' not in completed_shifts:
            kb.append([
                InlineKeyboardButton(
                    text=f"{pretty('e')} СТАРТ",
                    callback_data="e_start",
                    style="primary",
                )
            ])

        if {'m', 'd', 'e'}.issubset(completed_shifts) and ('x' not in completed_shifts):
            kb.append([
                InlineKeyboardButton(
                    text=f"{pretty('x')} СТАРТ",
                    callback_data="x_start",
                    style="primary",
                )
            ])

    kb.append([InlineKeyboardButton(text="📅 Графік відключень", callback_data="schedule_today")])
    kb.append([InlineKeyboardButton(text="📥 ПРИЙОМ ПАЛИВА", callback_data="refill_init", style="primary")])
    kb.append([InlineKeyboardButton(text="🕘 Останні події", callback_data="events_last")])
    # FIX #25: Add Messages button
    kb.append([InlineKeyboardButton(text="📨 Повідомлення", callback_data="view_messages")])

    if role == 'admin':
        kb.append([InlineKeyboardButton(text="⚙️ АДМІН ПАНЕЛЬ", callback_data="admin_home", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- АДМІН ПАНЕЛЬ ---
def admin_panel() -> InlineKeyboardMarkup:
    """Admin panel with streamlined operations.

    Removed deprecated Correction menu - its functionality has been moved to:
    - Maintenance hours: TO menu (mnt_set_hours)
    - Fuel correction: Direct fuel management in appropriate contexts
    - Consumption rate: Generator-specific settings

    Priority levels:
    - High (primary/blue): Frequent operations (Sync, Schedule)
    - Normal (no style): Regular operations (Personnel, Drivers, Maintenance, Users)
    - Danger (red): Destructive operations (DB Cleanup)

    Returns:
        InlineKeyboardMarkup with admin operations
    """
    kb: list[list[InlineKeyboardButton]] = [
        # Row 1: Most frequent operations (2 in row)
        [
            InlineKeyboardButton(text="📅 Графік", callback_data="sched_select_date"),
            InlineKeyboardButton(text="🔄 Синхронізація", callback_data="sync_menu", style="primary"),
        ],
        # Row 2: Generator management (single button, important)
        [
            InlineKeyboardButton(text="🔄 Перемикання генераторів", callback_data="generator_switch"),
        ],
        # Row 3: People management (2 in row)
        [
            InlineKeyboardButton(text="👥 Персонал", callback_data="personnel_menu"),
            InlineKeyboardButton(text="🚛 Водії", callback_data="drivers_menu"),
        ],
        # Row 4: Maintenance operations (single, prominent)
        [
            InlineKeyboardButton(text="🛠 Меню ТО", callback_data="mnt_menu"),
        ],
        # Row 5: User management (single, less frequent)
        [
            InlineKeyboardButton(text="👥 ID Користувачів", callback_data="users_list"),
        ],
        # Row 6: Dangerous operation (isolated, red)
        [
            InlineKeyboardButton(text="🗑 Очистка БД", callback_data="db_cleanup_confirm", style="danger"),
        ],
        # Row 7: Navigation
        [
            InlineKeyboardButton(text="🏠 На головну", callback_data="main_menu"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- СИНХРОНІЗАЦІЯ (тільки розумна) ---
def sync_menu() -> InlineKeyboardMarkup:
    """Меню синхронізації - тільки розумна двонаправлена синхронізація.

    Старі окремі імпорт/експорт видалені для запобігання помилкам.
    Розумна синхронізація автоматично визначає що треба синхронізувати.
    Модулі sheets_import.py та sheets_export.py залишені як резервні утиліти.

    Returns:
        InlineKeyboardMarkup with smart sync option
    """
    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🧠 Розумна синхронізація", callback_data="sync_smart", style="primary")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- КОРЕКЦІЯ (DEPRECATED - залишено для зворотної сумісності) ---
def correction_menu() -> InlineKeyboardMarkup:
    """DEPRECATED: Correction menu is no longer used.

    Functionality moved to:
    - Hours correction: Maintenance menu (mnt_set_hours)
    - Fuel/consumption: Generator-specific settings

    This function is kept for backward compatibility but should not be called.

    Returns:
        InlineKeyboardMarkup with deprecation notice
    """
    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="⚠️ Меню корекції видалено", callback_data="admin_home")],
        [InlineKeyboardButton(text="🛠 Перейти до меню ТО", callback_data="mnt_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_to_corr() -> InlineKeyboardMarkup:
    """DEPRECATED: Redirects to admin home.

    Returns:
        InlineKeyboardMarkup with back to admin button
    """
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 До адмін-панелі", callback_data="admin_home")]])


# --- ГРАФІК ---
def schedule_date_selector(today_str: str, tom_str: str) -> InlineKeyboardMarkup:
    """Build date selector for schedule editing.

    Args:
        today_str: Today's date in YYYY-MM-DD format
        tom_str: Tomorrow's date in YYYY-MM-DD format

    Returns:
        InlineKeyboardMarkup with today/tomorrow buttons
    """
    d_today = datetime.strptime(today_str, "%Y-%m-%d").strftime("%d-%m")
    d_tom = datetime.strptime(tom_str, "%Y-%m-%d").strftime("%d-%m")

    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"Сьогодні ({d_today})", callback_data=f"sched_edit_{today_str}")],
        [InlineKeyboardButton(text=f"Завтра ({d_tom})", callback_data=f"sched_edit_{tom_str}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def schedule_grid(date_str: str, is_today_and_working: bool = False) -> InlineKeyboardMarkup:
    """Build 24-hour schedule grid for a specific date.

    Args:
        date_str: Date in YYYY-MM-DD format
        is_today_and_working: If True, shows notification button

    Returns:
        InlineKeyboardMarkup with 24 hour toggles (2 per row)
    """
    sched = db.get_schedule(date_str)
    kb: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for h in range(24):
        icon = "🔴" if sched.get(h) == 1 else "🟢"
        end_s = "24:00" if h == 23 else f"{(h + 1):02d}:00"
        btn = InlineKeyboardButton(text=f"{h:02d}:00 - {end_s} {icon}", callback_data=f"tog_{date_str}_{h}")
        row.append(btn)
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    if is_today_and_working:
        kb.append([InlineKeyboardButton(text="📢 Сповістити про зміни", callback_data=f"sched_notify_{date_str}")])

    kb.append([InlineKeyboardButton(text="🔙 До вибору дати", callback_data="sched_select_date")])

    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- ТО (НОВЕ МЕНЮ) ---
def maintenance_menu_new() -> InlineKeyboardMarkup:
    """Нове меню ТО з підтримкою двох генераторів.

    Returns:
        InlineKeyboardMarkup with maintenance operations
    """
    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="✅ Виконати ТО", callback_data="mnt_perform", style="primary")],
        [InlineKeyboardButton(text="📜 Історія ТО", callback_data="mnt_history")],
        [InlineKeyboardButton(text="⏱ Коригувати мотогодини", callback_data="mnt_set_hours")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- ТО (СТАРЕ МЕНЮ - для зворотної сумісності) ---
def maintenance_menu() -> InlineKeyboardMarkup:
    """Старе меню ТО - залишається для зворотної сумісності.

    Returns:
        InlineKeyboardMarkup (same as maintenance_menu_new)
    """
    return maintenance_menu_new()


def maintenance_action_menu() -> InlineKeyboardMarkup:
    """Меню вибору дій ТО.

    Returns:
        InlineKeyboardMarkup with oil, spark, and maintenance options
    """
    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🛢 Заміна мастила", callback_data="mnt_oil")],
        [InlineKeyboardButton(text="🕯 Заміна свічок", callback_data="mnt_spark")],
        [InlineKeyboardButton(text="🔧 Планове ТО", callback_data="mnt_maintenance")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="mnt_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- ВОДІЇ ---
def drivers_list(drivers: list[str]) -> InlineKeyboardMarkup:
    """Build driver selection keyboard.

    Args:
        drivers: List of driver names

    Returns:
        InlineKeyboardMarkup with driver buttons and cancel
    """
    kb: list[list[InlineKeyboardButton]] = []
    for d in drivers:
        kb.append([InlineKeyboardButton(text=d, callback_data=f"drv_{d}")])
    kb.append([InlineKeyboardButton(text="🔙 Скасувати", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_to_admin() -> InlineKeyboardMarkup:
    """Simple back to admin button.

    Returns:
        InlineKeyboardMarkup with single back button
    """
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_home")]])


def back_to_main() -> InlineKeyboardMarkup:
    """Simple back to main menu button.

    Returns:
        InlineKeyboardMarkup with single back button
    """
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 На головну", callback_data="main_menu")]])


def back_to_mnt() -> InlineKeyboardMarkup:
    """Simple back to maintenance menu button.

    Returns:
        InlineKeyboardMarkup with single back button
    """
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="mnt_menu")]])


def after_add_menu() -> InlineKeyboardMarkup:
    """Universal 'after add' menu for both drivers and personnel.

    Returns:
        InlineKeyboardMarkup with back to admin button
    """
    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🔙 В адмінку", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
