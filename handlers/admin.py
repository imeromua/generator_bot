from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest # 👈 Додано імпорт помилки
from datetime import datetime
import config
import database.db_api as db
from keyboards.builders import (
    admin_panel, schedule_grid, report_period, 
    back_to_admin, after_add_menu, maintenance_menu, back_to_mnt
)
from services.excel_report import generate_report

router = Router()

class AddDriverForm(StatesGroup):
    name = State()

class SetHoursForm(StatesGroup):
    hours = State()

# --- ВХІД В АДМІНКУ ---
@router.callback_query(F.data == "admin_home")
async def adm_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    await state.clear()
    await cb.message.edit_text("⚙️ <b>Адмін Панель</b>", reply_markup=admin_panel())

# --- МЕНЮ ТО (Виправлено) ---
@router.callback_query(F.data == "mnt_menu")
async def mnt_view(cb: types.CallbackQuery):
    st = db.get_state()
    txt = (f"🛠 <b>Технічне Обслуговування</b>\n\n"
           f"⏱ Загальний пробіг: <b>{st['total_hours']:.1f} год</b>\n"
           f"🛢 Після заміни мастила: <b>{(st['total_hours'] - st['last_oil']):.1f} год</b>\n"
           f"🕯 Після заміни свічок: <b>{(st['total_hours'] - st['last_spark']):.1f} год</b>")
    
    try:
        # Спроба оновити текст
        await cb.message.edit_text(txt, reply_markup=maintenance_menu())
    except TelegramBadRequest:
        # Якщо текст той самий - ігноруємо помилку
        await cb.answer()

# --- 1. ЗАМІНА МАСТИЛА ---
@router.callback_query(F.data == "mnt_oil")
async def mnt_oil(cb: types.CallbackQuery):
    user = db.get_user(cb.from_user.id)
    db.record_maintenance("oil", user[1])
    await cb.answer("✅ Мастило замінено! Лічильник скинуто.", show_alert=True)
    await mnt_view(cb) # Оновлюємо текст меню

# --- 2. ЗАМІНА СВІЧОК ---
@router.callback_query(F.data == "mnt_spark")
async def mnt_spark(cb: types.CallbackQuery):
    user = db.get_user(cb.from_user.id)
    db.record_maintenance("spark", user[1])
    await cb.answer("✅ Свічки замінено! Лічильник скинуто.", show_alert=True)
    await mnt_view(cb)

# --- 3. РУЧНЕ КОРИГУВАННЯ ГОДИН ---
@router.callback_query(F.data == "mnt_set_hours")
async def ask_hours(cb: types.CallbackQuery, state: FSMContext):
    st = db.get_state()
    await cb.message.edit_text(
        f"⏱ Поточний пробіг: <b>{st['total_hours']:.1f}</b>\n\n"
        f"Введіть нове значення (цифри, наприклад 120.5):",
        reply_markup=back_to_mnt()
    )
    await state.set_state(SetHoursForm.hours)

@router.message(SetHoursForm.hours)
async def save_hours(msg: types.Message, state: FSMContext):
    try:
        val = float(msg.text.replace(",", "."))
        db.set_total_hours(val)
        await msg.answer(f"✅ Пробіг встановлено: <b>{val} год</b>")
        await state.clear()
        
        # Повертаємось в меню ТО
        st = db.get_state()
        txt = (f"🛠 <b>Технічне Обслуговування</b>\n\n"
               f"⏱ Загальний пробіг: <b>{st['total_hours']:.1f} год</b>\n"
               f"🛢 Після заміни мастила: <b>{(st['total_hours'] - st['last_oil']):.1f} год</b>\n"
               f"🕯 Після заміни свічок: <b>{(st['total_hours'] - st['last_spark']):.1f} год</b>")
        await msg.answer(txt, reply_markup=maintenance_menu())
        
    except ValueError:
        await msg.answer("❌ Введіть коректне число (наприклад 100.5)")

# --- ГРАФІК ---
@router.callback_query(F.data == "sched_today")
async def sched_view(cb: types.CallbackQuery):
    today = datetime.now(config.KYIV).strftime("%Y-%m-%d")
    await cb.message.edit_text(f"📅 Графік на {today}\n(🔴 - немає світла)", reply_markup=schedule_grid(today))

@router.callback_query(F.data.startswith("tog_"))
async def tog_hour(cb: types.CallbackQuery):
    _, date, hour = cb.data.split("_")
    db.toggle_schedule(date, int(hour))
    await cb.message.edit_reply_markup(reply_markup=schedule_grid(date))

# --- ЗВІТИ ---
@router.callback_query(F.data == "download_report")
async def report_ask(cb: types.CallbackQuery):
    await cb.message.edit_text("📊 Оберіть період звіту:", reply_markup=report_period())

@router.callback_query(F.data.in_({"rep_current", "rep_prev"}))
async def report_gen(cb: types.CallbackQuery):
    await cb.message.edit_text("⏳ Формую файл...")
    period = "current" if cb.data == "rep_current" else "prev"
    file_path, caption = await generate_report(period)
    if not file_path:
        await cb.message.edit_text(caption, reply_markup=admin_panel())
        return
    file = types.FSInputFile(file_path)
    await cb.message.answer_document(file, caption=caption)
    import os
    os.remove(file_path)
    await cb.answer()

# --- ЮЗЕРИ ---
@router.callback_query(F.data == "users_list")
async def users_view(cb: types.CallbackQuery):
    users = db.get_all_users()
    txt = "👥 <b>Користувачі в БД:</b>\n\n"
    for uid, name in users:
        txt += f"👤 {name}\n🆔 <code>{uid}</code>\n\n"
    txt += "<i>Натисніть на ID, щоб скопіювати.</i>"
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]])
    await cb.message.edit_text(txt, reply_markup=kb)

# --- ВОДІЇ ---
@router.callback_query(F.data == "add_driver_start")
async def drv_add(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("✍️ Введіть Прізвище водія:", reply_markup=back_to_admin())
    await state.set_state(AddDriverForm.name)

@router.message(AddDriverForm.name)
async def drv_save(msg: types.Message, state: FSMContext):
    db.add_driver(msg.text)
    await msg.answer(f"✅ Водій {msg.text} доданий.", reply_markup=after_add_menu())
    await state.clear()