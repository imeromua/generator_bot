from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import database.db_api as db

def main_dashboard(role, is_on):
    """Головний пульт керування"""
    kb = [
        [InlineKeyboardButton(text="🌅 Ранок СТАРТ", callback_data="m_start"),
         InlineKeyboardButton(text="🏁 Ранок СТОП", callback_data="m_end")],
        [InlineKeyboardButton(text="☀️ День СТАРТ", callback_data="d_start"),
         InlineKeyboardButton(text="🏁 День СТОП", callback_data="d_end")],
        [InlineKeyboardButton(text="🌙 Вечір СТАРТ", callback_data="e_start"),
         InlineKeyboardButton(text="🏁 Вечір СТОП", callback_data="e_end")],
        [InlineKeyboardButton(text="📥 ПРИЙОМ ПАЛИВА", callback_data="refill_init")]
    ]
    
    if role == 'admin':
        kb.append([InlineKeyboardButton(text="⚙️ АДМІН ПАНЕЛЬ", callback_data="admin_home")])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_panel():
    """Меню адміністратора"""
    kb = [
        [InlineKeyboardButton(text="📅 Графік (Клікер)", callback_data="sched_today")],
        [InlineKeyboardButton(text="📥 Скачати Звіт (Excel)", callback_data="download_report")],
        [InlineKeyboardButton(text="👥 ID Користувачів", callback_data="users_list")],
        [InlineKeyboardButton(text="🚛 Водії (+)", callback_data="add_driver_start")],
        # ЗМІНИЛИ: Тепер тут вхід в підменю ТО
        [InlineKeyboardButton(text="🛠 Меню ТО (Мастило/Години)", callback_data="mnt_menu")],
        [InlineKeyboardButton(text="🔙 На головну", callback_data="home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# 👇 НОВЕ МЕНЮ ТО
def maintenance_menu():
    kb = [
        [InlineKeyboardButton(text="⏱ Коригувати мотогодини", callback_data="mnt_set_hours")],
        [InlineKeyboardButton(text="🛢 Заміна мастила", callback_data="mnt_oil")],
        [InlineKeyboardButton(text="🕯 Заміна свічок", callback_data="mnt_spark")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def schedule_grid(date_str):
    """Сітка 4x6 годин"""
    sched = db.get_schedule(date_str)
    kb = []
    row = []
    for h in range(24):
        icon = "🔴" if sched.get(h) == 1 else "🟢"
        btn = InlineKeyboardButton(text=f"{h:02} {icon}", callback_data=f"tog_{date_str}_{h}")
        row.append(btn)
        if len(row) == 4:
            kb.append(row)
            row = []
            
    if row: kb.append(row)
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")])
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
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="home")]])

# Кнопка для повернення в ТО
def back_to_mnt():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="mnt_menu")]])

def after_add_menu():
    kb = [
        [InlineKeyboardButton(text="➕ Додати ще", callback_data="add_driver_start")],
        [InlineKeyboardButton(text="🔙 В адмінку", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)