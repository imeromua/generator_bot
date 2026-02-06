from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timedelta
import logging
import config
import database.db_api as db
from keyboards.builders import (
    admin_panel, schedule_grid, report_period, 
    back_to_admin, after_add_menu, maintenance_menu, back_to_mnt,
    schedule_date_selector 
)
from services.excel_report import generate_report

router = Router()
logger = logging.getLogger(__name__)

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
    logger.info(f"👤 Адмін {cb.from_user.id} відкрив панель")
    await cb.message.edit_text("⚙️ <b>Адмін Панель</b>", reply_markup=admin_panel())

# --- 1. ГРАФІК: ВИБІР ДАТИ ---
@router.callback_query(F.data == "sched_select_date")
async def sched_select(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    now = datetime.now(config.KYIV)
    
    today_str = now.strftime("%Y-%m-%d")
    tom_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    
    try:
        end_time_limit = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        is_evening = now.time() > end_time_limit
    except ValueError:
        logger.error(f"Неправильний формат WORK_END_TIME: {config.WORK_END_TIME}")
        is_evening = False
    
    hint = "🌙 Вже вечір, заповнюємо на <b>ЗАВТРА</b>?" if is_evening else "☀️ День, редагуємо <b>СЬОГОДНІ</b>?"
    
    await cb.message.edit_text(
        f"📅 <b>Налаштування графіка</b>\n{hint}", 
        reply_markup=schedule_date_selector(today_str, tom_str)
    )

# --- 2. ГРАФІК: СІТКА ---
@router.callback_query(F.data.startswith("sched_edit_"))
async def sched_edit(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    try:
        date_str = cb.data.split("_")[2]
        pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (IndexError, ValueError) as e:
        logger.error(f"Помилка парсингу дати: {e}")
        return await cb.answer("❌ Неправильний формат дати", show_alert=True)
    
    now = datetime.now(config.KYIV)
    today_iso = now.strftime("%Y-%m-%d")
    
    try:
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
    except ValueError:
        logger.error(f"Неправильний формат WORK_START_TIME: {config.WORK_START_TIME}")
        start_t = datetime.strptime("07:30", "%H:%M").time()
    
    is_hot_edit = False
    if date_str == today_iso and now.time() > start_t:
        is_hot_edit = True
        
    txt = f"📅 Графік на <b>{pretty_date}</b>\n(🔴 - немає світла)\n"
    if is_hot_edit:
        txt += "\n⚠️ <i>Ви змінюєте графік поточного дня. Не забудьте натиснути 'Сповістити'!</i>"

    try:
        await cb.message.edit_text(txt, reply_markup=schedule_grid(date_str, is_hot_edit))
    except TelegramBadRequest as e:
        logger.warning(f"TelegramBadRequest при редагуванні графіка: {e}")
        await cb.answer()

# --- 3. ГРАФІК: КЛІКЕР ---
@router.callback_query(F.data.startswith("tog_"))
async def tog_hour(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    try:
        _, date_str, hour = cb.data.split("_")
        db.toggle_schedule(date_str, int(hour))
        
        now = datetime.now(config.KYIV)
        today_iso = now.strftime("%Y-%m-%d")
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        is_hot_edit = (date_str == today_iso and now.time() > start_t)
        
        try:
            await cb.message.edit_reply_markup(reply_markup=schedule_grid(date_str, is_hot_edit))
        except TelegramBadRequest:
            pass
        
        await cb.answer()
    except Exception as e:
        logger.error(f"Помилка toggle графіка: {e}")
        await cb.answer("❌ Помилка", show_alert=True)

# --- 4. ГРАФІК: СПОВІЩЕННЯ ---
@router.callback_query(F.data.startswith("sched_notify_"))
async def sched_notify(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    try:
        date_str = cb.data.split("_")[2]
        sched = db.get_schedule(date_str)
        pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception as e:
        logger.error(f"Помилка отримання графіка: {e}")
        return await cb.answer("❌ Помилка отримання графіка", show_alert=True)
    
    txt = f"⚡ <b>УВАГА! ЗМІНА ГРАФІКА ({pretty_date})</b>\n\n"
    for h in range(8, 22):
        icon = "🔴" if sched.get(h) == 1 else "🟢"
        txt += f"{h:02}:00 {icon}  "
        if h == 14:
            txt += "\n"
    txt += "\n\n🔴 - Відключення\n🟢 - Світло є"
    
    users = db.get_all_users()
    count = 0
    fail_count = 0
    
    for uid, uname in users:
        try:
            await cb.bot.send_message(uid, txt)
            count += 1
            await asyncio.sleep(0.05)  # Невелика затримка
        except Exception as e:
            logger.warning(f"Не вдалося надіслати {uname} (ID: {uid}): {e}")
            fail_count += 1
    
    logger.info(f"📢 Розсилка графіка: {count} успішно, {fail_count} помилок")
    await cb.answer(f"✅ Надіслано {count} користувачам", show_alert=True)
    await sched_edit(cb)

# --- МЕНЮ ТО ---
@router.callback_query(F.data == "mnt_menu")
async def mnt_view(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    st = db.get_state()
    txt = (f"🛠 <b>Технічне Обслуговування</b>\n\n"
           f"⏱ Загальний пробіг: <b>{st['total_hours']:.1f} год</b>\n"
           f"🛢 Після заміни мастила: <b>{(st['total_hours'] - st['last_oil']):.1f} год</b>\n"
           f"🕯 Після заміни свічок: <b>{(st['total_hours'] - st['last_spark']):.1f} год</b>")
    
    try:
        await cb.message.edit_text(txt, reply_markup=maintenance_menu())
    except TelegramBadRequest:
        await cb.answer()

@router.callback_query(F.data == "mnt_oil")
async def mnt_oil(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    user = db.get_user(cb.from_user.id)
    db.record_maintenance("oil", user[1])
    logger.info(f"🛢 {user[1]} виконав заміну мастила")
    await cb.answer("✅ Мастило замінено!", show_alert=True)
    await mnt_view(cb)

@router.callback_query(F.data == "mnt_spark")
async def mnt_spark(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    user = db.get_user(cb.from_user.id)
    db.record_maintenance("spark", user[1])
    logger.info(f"🕯 {user[1]} виконав заміну свічок")
    await cb.answer("✅ Свічки замінено!", show_alert=True)
    await mnt_view(cb)

@router.callback_query(F.data == "mnt_set_hours")
async def ask_hours(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    st = db.get_state()
    await cb.message.edit_text(f"⏱ Поточний: <b>{st['total_hours']:.1f}</b>\nВведіть нове:", reply_markup=back_to_mnt())
    await state.set_state(SetHoursForm.hours)

@router.message(SetHoursForm.hours)
async def save_hours(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")
    
    try:
        val_text = msg.text.replace(",", ".").strip()
        val = float(val_text)
        
        if val < 0:
            return await msg.answer("❌ Значення не може бути від'ємним", reply_markup=back_to_mnt())
        
        if val > 100000:
            return await msg.answer("❌ Значення занадто велике (максимум 100000)", reply_markup=back_to_mnt())
        
        db.set_total_hours(val)
        user = db.get_user(msg.from_user.id)
        logger.info(f"⏱ {user[1]} встановив мотогодини: {val}")
        await msg.answer(f"✅ Встановлено: <b>{val} год</b>")
        
        st = db.get_state()
        txt = (f"🛠 <b>Технічне Обслуговування</b>\n\n"
               f"⏱ Загальний пробіг: <b>{st['total_hours']:.1f} год</b>\n"
               f"🛢 Після заміни мастила: <b>{(st['total_hours'] - st['last_oil']):.1f} год</b>\n"
               f"🕯 Після заміни свічок: <b>{(st['total_hours'] - st['last_spark']):.1f} год</b>")
        
        await msg.answer(txt, reply_markup=maintenance_menu())
        await state.clear()
    except ValueError:
        await msg.answer("❌ Введіть число (наприклад 100.5)", reply_markup=back_to_mnt())

# --- ЗВІТИ ---
@router.callback_query(F.data == "download_report")
async def report_ask(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    await cb.message.edit_text("📊 Період:", reply_markup=report_period())

@router.callback_query(F.data.in_({"rep_current", "rep_prev"}))
async def report_gen(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    try:
        await cb.message.edit_text("⏳ Генерую звіт, зачекайте...")
        period = "current" if cb.data == "rep_current" else "prev"
        
        file_path, caption = await generate_report(period)
        
        if not file_path:
            await cb.message.edit_text(caption, reply_markup=admin_panel())
            return
        
        file = types.FSInputFile(file_path)
        await cb.message.answer_document(file, caption=caption)
        
        import os
        os.remove(file_path)
        logger.info(f"📊 Звіт згенеровано: {period}")
        
        await cb.message.delete()
        await cb.answer("✅ Звіт готовий!")
        
    except Exception as e:
        logger.error(f"Помилка генерації звіту: {e}", exc_info=True)
        await cb.message.edit_text(f"❌ Помилка генерації звіту: {str(e)}", reply_markup=admin_panel())

# --- ЮЗЕРИ ---
@router.callback_query(F.data == "users_list")
async def users_view(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    users = db.get_all_users()
    txt = "👥 <b>Користувачі в БД:</b>\n\n"
    
    if not users:
        txt += "<i>Поки немає зареєстрованих користувачів</i>"
    else:
        for uid, name in users:
            txt += f"👤 {name}\n🆔 <code>{uid}</code>\n\n"
        txt += "<i>Натисніть на ID, щоб скопіювати.</i>"
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]])
    await cb.message.edit_text(txt, reply_markup=kb)

# --- ВОДІЇ ---
@router.callback_query(F.data == "add_driver_start")
async def drv_add(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    await cb.message.edit_text("✍️ Введіть прізвище водія:", reply_markup=back_to_admin())
    await state.set_state(AddDriverForm.name)

@router.message(AddDriverForm.name)
async def drv_save(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")
    
    driver_name = msg.text.strip()
    
    if not driver_name:
        return await msg.answer("❌ Ім'я не може бути порожнім", reply_markup=back_to_admin())
    
    if len(driver_name) > 50:
        return await msg.answer("❌ Ім'я занадто довге (максимум 50 символів)", reply_markup=back_to_admin())
    
    success = db.add_driver(driver_name)
    
    if success:
        user = db.get_user(msg.from_user.id)
        logger.info(f"🚛 {user[1]} додав водія: {driver_name}")
        await msg.answer(f"✅ {driver_name} доданий.", reply_markup=after_add_menu())
    else:
        await msg.answer(f"⚠️ Водій {driver_name} вже існує.", reply_markup=after_add_menu())
    
    await state.clear()

# Додаємо імпорт для asyncio
import asyncio
