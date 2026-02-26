from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
import database.db_api as db
from datetime import datetime
import config

# --- ГОЛОВНЕ МЕНЮ ---
def main_dashboard(role, active_shift, completed_shifts):
    kb = []

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

    # Mini App button (якщо WEBAPP_URL налаштовано)
    if config.WEBAPP_URL:
        kb.append([InlineKeyboardButton(
            text="📱 Mini App",
            web_app=WebAppInfo(url=config.WEBAPP_URL),
        )])

    if role == 'admin':
        kb.append([InlineKeyboardButton(text="⚙️ АДМІН ПАНЕЛЬ", callback_data="admin_home", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- АДМІН ПАНЕЛЬ ---
def admin_panel():
    """Admin panel with streamlined operations.
    
    Removed deprecated Correction menu - its functionality has been moved to:
    - Maintenance hours: TO menu (mnt_set_hours)
    - Fuel correction: Direct fuel management in appropriate contexts
    - Consumption rate: Generator-specific settings
    
    Priority levels:
    - High (primary/blue): Frequent operations (Sync, Schedule)
    - Normal (no style): Regular operations (Personnel, Drivers, Maintenance, Users)
    - Danger (red): Destructive operations (DB Cleanup)
    """
    kb = [
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
def sync_menu():
    """Меню синхронізації - тільки розумна двонаправлена синхронізація.
    
    Старі окремі імпорт/експорт видалені для запобігання помилкам.
    Розумна синхронізація автоматично визначає що треба синхронізувати.
    Модулі sheets_import.py та sheets_export.py залишені як резервні утиліти.
    """
    kb = [
        [InlineKeyboardButton(text="🧠 Розумна синхронізація", callback_data="sync_smart", style="primary")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- КОРЕКЦІЯ (DEPRECATED - залишено для зворотної сумісності) ---
def correction_menu():
    """DEPRECATED: Correction menu is no longer used.
    
    Functionality moved to:
    - Hours correction: Maintenance menu (mnt_set_hours)
    - Fuel/consumption: Generator-specific settings
    
    This function is kept for backward compatibility but should not be called.
    """
    kb = [
        [InlineKeyboardButton(text="⚠️ Меню корекції видалено", callback_data="admin_home")],
        [InlineKeyboardButton(text="🛠 Перейти до меню ТО", callback_data="mnt_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_to_corr():
    """DEPRECATED: Redirects to admin home."""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 До адмін-панелі", callback_data="admin_home")]])


# --- ГРАФІК ---
def schedule_date_selector(today_str, tom_str):
    d_today = datetime.strptime(today_str, "%Y-%m-%d").strftime("%d-%m")
    d_tom = datetime.strptime(tom_str, "%Y-%m-%d").strftime("%d-%m")

    kb = [
        [InlineKeyboardButton(text=f"Сьогодні ({d_today})", callback_data=f"sched_edit_{today_str}")],
        [InlineKeyboardButton(text=f"Завтра ({d_tom})", callback_data=f"sched_edit_{tom_str}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def schedule_grid(date_str, is_today_and_working=False):
    sched = db.get_schedule(date_str)
    kb = []
    row = []

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
def maintenance_menu_new():
    """Нове меню ТО з підтримкою двох генераторів."""
    kb = [
        [InlineKeyboardButton(text="✅ Виконати ТО", callback_data="mnt_perform", style="primary")],
        [InlineKeyboardButton(text="📜 Історія ТО", callback_data="mnt_history")],
        [InlineKeyboardButton(text="⏱ Коригувати мотогодини", callback_data="mnt_set_hours")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- ТО (СТАРЕ МЕНЮ - для зворотної сумісності) ---
def maintenance_menu():
    """Старе меню ТО - залишається для зворотної сумісності."""
    return maintenance_menu_new()


def maintenance_action_menu():
    """Меню вибору дій ТО."""
    kb = [
        [InlineKeyboardButton(text="🛢 Заміна мастила", callback_data="mnt_oil")],
        [InlineKeyboardButton(text="🕯 Заміна свічок", callback_data="mnt_spark")],
        [InlineKeyboardButton(text="🔧 Планове ТО", callback_data="mnt_maintenance")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="mnt_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- ВОДІЇ ---
def drivers_list(drivers):
    kb = []
    for d in drivers:
        kb.append([InlineKeyboardButton(text=d, callback_data=f"drv_{d}")])
    kb.append([InlineKeyboardButton(text="🔙 Скасувати", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_to_admin():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_home")]])


def back_to_main():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 На головну", callback_data="main_menu")]])


def back_to_mnt():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="mnt_menu")]])


def after_add_menu():
    """Universal 'after add' menu for both drivers and personnel."""
    kb = [
        [InlineKeyboardButton(text="🔙 В адмінку", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
