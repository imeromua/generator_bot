from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import database.db_api as db

def main_dashboard(role, active_shift, completed_shifts):
    """
    Головний пульт (Розумна версія)
    active_shift: 'm_start', 'none', ...
    completed_shifts: {'m', 'd', 'e'} - зміни, які вже були сьогодні
    """
    kb = []
    
    # 1. Якщо генератор ПРАЦЮЄ -> Показуємо ТІЛЬКИ кнопку СТОП для поточної зміни
    if active_shift != 'none':
        # active_shift = 'm_start' -> нам треба код 'm'
        code = active_shift.split("_")[0]
        
        names = {"m": "🌅 Ранок", "d": "☀️ День", "e": "🌙 Вечір", "x": "⚡ Екстра"}
        name = names.get(code, code.upper())
        
        # Єдина кнопка - СТОП
        kb.append([InlineKeyboardButton(text=f"🏁 {name} СТОП", callback_data=f"{code}_end")])
        
    else:
        # 2. Якщо генератор СТОЇТЬ -> Показуємо доступні старти
        
        # Ранок (якщо ще не був)
        if 'm' not in completed_shifts:
            kb.append([InlineKeyboardButton(text="🌅 Ранок СТАРТ", callback_data="m_start")])
            
        # День (якщо ще не був)
        if 'd' not in completed_shifts:
            kb.append([InlineKeyboardButton(text="☀️ День СТАРТ", callback_data="d_start")])
            
        # Вечір (якщо ще не був)
        if 'e' not in completed_shifts:
            kb.append([InlineKeyboardButton(text="🌙 Вечір СТАРТ", callback_data="e_start")])
            
        # ЕКСТРА (Тільки якщо Ранок, День і Вечір ВЖЕ були)
        if {'m', 'd', 'e'}.issubset(completed_shifts):
             kb.append([InlineKeyboardButton(text="⚡ Екстра СТАРТ", callback_data="x_start")])

    # 3. Заправка (Завжди доступна)
    kb.append([InlineKeyboardButton(text="📥 ПРИЙОМ ПАЛИВА", callback_data="refill_init")])
    
    # 4. Адмінка (Завжди, якщо адмін)
    if role == 'admin':
        kb.append([InlineKeyboardButton(text="⚙️ АДМІН ПАНЕЛЬ", callback_data="admin_home")])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- Інші функції без змін ---
def admin_panel():
    kb = [
        [InlineKeyboardButton(text="📅 Графік (Клікер)", callback_data="sched_today")],
        [InlineKeyboardButton(text="📥 Скачати Звіт (Excel)", callback_data="download_report")],
        [InlineKeyboardButton(text="👥 ID Користувачів", callback_data="users_list")],
        [InlineKeyboardButton(text="🚛 Водії (+)", callback_data="add_driver_start")],
        [InlineKeyboardButton(text="🛠 Меню ТО (Мастило/Години)", callback_data="mnt_menu")],
        [InlineKeyboardButton(text="🔙 На головну", callback_data="home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def maintenance_menu():
    kb = [
        [InlineKeyboardButton(text="⏱ Коригувати мотогодини", callback_data="mnt_set_hours")],
        [InlineKeyboardButton(text="🛢 Заміна мастила", callback_data="mnt_oil")],
        [InlineKeyboardButton(text="🕯 Заміна свічок", callback_data="mnt_spark")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def schedule_grid(date_str):
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

def back_to_mnt():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="mnt_menu")]])

def after_add_menu():
    kb = [
        [InlineKeyboardButton(text="➕ Додати ще", callback_data="add_driver_start")],
        [InlineKeyboardButton(text="🔙 В адмінку", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)