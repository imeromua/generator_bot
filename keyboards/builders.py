from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import database.db_api as db
from datetime import datetime
import config

# --- ГОЛОВНЕ МЕНЮ ---
def main_dashboard(role, active_shift, completed_shifts):
    kb = []

    def pretty(code: str) -> str:
        return {
            "m": "🟬 Зміна 1",
            "d": "🟪 Зміна 2",
            "e": "🟪 Зміна 3",
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

    if role == 'admin':
        kb.append([InlineKeyboardButton(text="⚙️ АДМІН ПАНЕЛЬ", callback_data="admin_home", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- АДМІН ПАНЕЛЬ ---
def admin_panel():
    kb = [
        [InlineKeyboardButton(text="📅 Графік Відключень", callback_data="sched_select_date")],
        [InlineKeyboardButton(text="🔄 Синхронізація", callback_data="sync_menu")],
        [InlineKeyboardButton(text="🧮 Корекція", callback_data="corr_menu")],
        [InlineKeyboardButton(text="👥 Персонал", callback_data="personnel_menu")],
        [InlineKeyboardButton(text="👥 ID Користувачів", callback_data="users_list")],
        [InlineKeyboardButton(text="🚛 Водії (+)", callback_data="add_driver_start")],
        [InlineKeyboardButton(text="🛠 Меню ТО (Мастило/Години)", callback_data="mnt_menu")],
        [InlineKeyboardButton(text="🗑 Очистка БД", callback_data="db_cleanup_confirm")],
        [InlineKeyboardButton(text="🔙 На головну", callback_data="home")]
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


# --- КОРЕКЦІЯ ---
def correction_menu():
    kb = [
        [InlineKeyboardButton(text="⛽️ Корекція залишку палива", callback_data="corr_fuel_set")],
        [InlineKeyboardButton(text="📊 Корекція витрати палива (л/год)", callback_data="corr_fuel_consumption_set")],
        [InlineKeyboardButton(text="⏱ Корекція мотогодин", callback_data="corr_total_hours_set")],
        [InlineKeyboardButton(text="🛢 Корекція: остання заміна мастила", callback_data="corr_last_oil_set")],
        [InlineKeyboardButton(text="🕯 Корекція: остання заміна свічок", callback_data="corr_last_spark_set")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_to_corr():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="corr_menu")]])


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


# --- ТО ---
def maintenance_menu():
    kb = [
        [InlineKeyboardButton(text="⏱ Коригувати мотогодини", callback_data="mnt_set_hours")],
        [InlineKeyboardButton(text="🛢 Заміна мастила", callback_data="mnt_oil")],
        [InlineKeyboardButton(text="🕯 Заміна свічок", callback_data="mnt_spark")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- ВОДІЇ ---
def drivers_list(drivers):
    kb = []
    for d in drivers:
        kb.append([InlineKeyboardButton(text=d, callback_data=f"drv_{d}")])
    kb.append([InlineKeyboardButton(text="🔙 Скасувати", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_to_admin():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_home")]])


def back_to_main():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 На головну", callback_data="home")]])


def back_to_mnt():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="mnt_menu")]])


def after_add_menu():
    kb = [
        [InlineKeyboardButton(text="➕ Додати ще", callback_data="add_driver_start")],
        [InlineKeyboardButton(text="🔙 В адмінку", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
