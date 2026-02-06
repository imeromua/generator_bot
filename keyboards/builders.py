from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import database.db_api as db
from datetime import datetime
import config

# --- ГОЛОВНЕ МЕНЮ ---
def main_dashboard(role, active_shift, completed_shifts):
    kb = []

    def pretty(code: str) -> str:
        return {
            "m": "🟦 Зміна 1",
            "d": "🟩 Зміна 2",
            "e": "🟪 Зміна 3",
            "x": "⚡ Екстра",
        }.get(code, code.upper())

    if active_shift != 'none':
        code = active_shift.split("_")[0]
        kb.append([InlineKeyboardButton(text=f"🏁 {pretty(code)} СТОП", callback_data=f"{code}_end")])
    else:
        # Показуємо старт тільки наступної зміни по черзі (1 -> 2 -> 3)
        if 'm' not in completed_shifts:
            kb.append([InlineKeyboardButton(text=f"{pretty('m')} СТАРТ", callback_data="m_start")])
        elif 'd' not in completed_shifts:
            kb.append([InlineKeyboardButton(text=f"{pretty('d')} СТАРТ", callback_data="d_start")])
        elif 'e' not in completed_shifts:
            kb.append([InlineKeyboardButton(text=f"{pretty('e')} СТАРТ", callback_data="e_start")])

        # ⚡ Екстра: показуємо тільки якщо 1/2/3 вже закриті, і сама Екстра ще не закрита
        if {'m', 'd', 'e'}.issubset(completed_shifts) and ('x' not in completed_shifts):
            kb.append([InlineKeyboardButton(text=f"{pretty('x')} СТАРТ", callback_data="x_start")])

    # Графік відключень доступний для всіх
    kb.append([InlineKeyboardButton(text="📅 Графік відключень", callback_data="schedule_today")])

    kb.append([InlineKeyboardButton(text="📥 ПРИЙОМ ПАЛИВА", callback_data="refill_init")])

    if role == 'admin':
        kb.append([InlineKeyboardButton(text="⚙️ АДМІН ПАНЕЛЬ", callback_data="admin_home")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- АДМІН ПАНЕЛЬ ---
def admin_panel():
    kb = [
        [InlineKeyboardButton(text="📅 Графік Відключень", callback_data="sched_select_date")],
        [InlineKeyboardButton(text="📥 Скачати Звіт (Excel)", callback_data="download_report")],
        [InlineKeyboardButton(text="👥 Персонал", callback_data="personnel_menu")],
        [InlineKeyboardButton(text="👥 ID Користувачів", callback_data="users_list")],
        [InlineKeyboardButton(text="🚛 Водії (+)", callback_data="add_driver_start")],
        [InlineKeyboardButton(text="🛠 Меню ТО (Мастило/Години)", callback_data="mnt_menu")],
        [InlineKeyboardButton(text="🔙 На головну", callback_data="home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- НОВЕ: Вибір дати (Сьогодні / Завтра) ---
def schedule_date_selector(today_str, tom_str):
    d_today = datetime.strptime(today_str, "%Y-%m-%d").strftime("%d-%m")
    d_tom = datetime.strptime(tom_str, "%Y-%m-%d").strftime("%d-%m")

    kb = [
        [InlineKeyboardButton(text=f"Сьогодні ({d_today})", callback_data=f"sched_edit_{today_str}")],
        [InlineKeyboardButton(text=f"Завтра ({d_tom})", callback_data=f"sched_edit_{tom_str}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- СІТКА ГРАФІКА (Оновлена) ---
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

# --- Інші допоміжні ---
def maintenance_menu():
    kb = [
        [InlineKeyboardButton(text="⏱ Коригувати мотогодини", callback_data="mnt_set_hours")],
        [InlineKeyboardButton(text="🛢 Заміна мастила", callback_data="mnt_oil")],
        [InlineKeyboardButton(text="🕯 Заміна свічок", callback_data="mnt_spark")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def drivers_list(drivers):
    kb = []
    for d in drivers:
        kb.append([InlineKeyboardButton(text=d, callback_data=f"drv_{d}")])
    kb.append([InlineKeyboardButton(text="🔙 Скасувати", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def report_period():
    kb = [
        [InlineKeyboardButton(text="📅 Цей місяць", callback_data="rep_current")],
        [InlineKeyboardButton(text="🗓 Минулий місяць", callback_data="rep_prev")],
        [InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_home")]
    ]
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
